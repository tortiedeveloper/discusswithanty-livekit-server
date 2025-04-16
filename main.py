import asyncio
import json
import datetime
import logging
import os
from dotenv import load_dotenv
import time
from typing import AsyncGenerator, Optional, Callable, Awaitable

# Imports
from openai import AsyncOpenAI # Diperlukan untuk generate_summary_with_llm versi direct call
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.rtc import DataPacket, DataPacketKind, RemoteParticipant
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import openai, silero, groq
from api import AssistantFnc
# from api import SendDataCallback
from mem0 import MemoryClient

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('livekit').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)
logging.getLogger('mem0').setLevel(logging.INFO)
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('assistant-api').setLevel(logging.INFO)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

# --- Env Vars & Mem0 Setup ---
load_dotenv()
logger.info("Environment variables loaded.")
if not os.getenv("PERPLEXITY_API_KEY"):
    logger.warning("PERPLEXITY_API_KEY not found in environment variables. Internet search will fail.")
if not os.getenv("OPENAI_API_KEY"):
    logger.error("FATAL: OPENAI_API_KEY not found in environment variables. Summarization will fail.")

mem0_client = None
try:
    if api_key := os.getenv("MEM0_API_KEY"):
        logger.info("Initializing Mem0 Client...")
        mem0_client = MemoryClient()
        logger.info("Mem0 Client object created.")
    else:
        logger.warning("MEM0_API_KEY not found. Mem0 features disabled.")
except Exception as e:
    logger.error(f"Failed to initialize Mem0 Client: {e}", exc_info=True)

# --- Konstanta ---
SEMANTIC_QUERY_GENERAL_STARTUP = (
    "Key points, facts, preferences, user's name, user's recent mood, "
    "and user's recent concerns shared in previous conversations"
)
MEM0_SEARCH_TIMEOUT = 15.0
LLM_GREETING_TIMEOUT = 10.0

# --- Helper Functions ---
async def search_mem0_with_timeout(user_id: str, query: str, limit: int = 5):
    if not mem0_client:
        logger.warning("Mem0 client not available for search.")
        return None
    try:
        start_time = time.time()
        logger.debug(f"Starting Mem0 search for user '{user_id}' (limit: {limit})")
        search_coro = asyncio.to_thread(
            mem0_client.search, user_id=user_id, query=query, limit=limit
        )
        result = await asyncio.wait_for(search_coro, timeout=MEM0_SEARCH_TIMEOUT)
        logger.debug(f"Finished Mem0 search in {time.time() - start_time:.2f}s")
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Mem0 search timed out after {MEM0_SEARCH_TIMEOUT}s for query: '{query[:100]}...'")
        return None
    except Exception as e:
        logger.error(f"Error during Mem0 search: {e}", exc_info=True)
        return None

async def _collect_llm_stream(stream: AsyncGenerator[llm.ChatChunk, None]) -> str:
    full_response = ""
    chunk_index = 0
    logger.debug("Starting to collect LLM stream (for VoiceAssistant)...")
    try:
        async for chunk in stream:
            chunk_index += 1
            chunk_content = getattr(chunk, 'content', None)
            chunk_type = type(chunk).__name__
            logger.debug(f"  VA Stream Chunk #{chunk_index}: Type={chunk_type}, Content='{chunk_content}'")
            if chunk_content:
                full_response += chunk_content
        logger.debug(f"Finished collecting VA LLM stream after {chunk_index} chunks.")
    except Exception as e:
        logger.error(f"Error while iterating VA LLM stream at chunk #{chunk_index + 1}: {e}", exc_info=True)
        raise
    return full_response.strip()

# --- Fungsi Generate Summary (Menggunakan AsyncOpenAI Langsung) ---
async def generate_summary_with_llm(llm_plugin: Optional[llm.LLM], transcript: str) -> str:
    """
    Menghasilkan ringkasan rapat menggunakan PANGGILAN API OPENAI LANGSUNG via AsyncOpenAI.
    Parameter llm_plugin diabaikan.
    """
    if not transcript or not transcript.strip():
        logger.warning("Attempted to summarize empty transcript.")
        return "Error: Transkrip kosong."

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment variables for direct summarization call.")
        return "Error: Konfigurasi API Key OpenAI tidak ditemukan."

    MODEL_TO_USE = "gpt-4o" # Pastikan ini model yang berhasil

    summary_prompt = (
        "Anda adalah asisten AI yang bertugas merangkum transkrip berikut dalam Bahasa Indonesia. "
        "Sebutkan topik utama yang dibahas. Jika ada keputusan atau item tindakan yang jelas, sebutkan juga. "
        "Jika tidak ada, cukup rangkum poin utamanya saja secara singkat.\n\n"
        "Transkrip:\n"
        f"{transcript}\n\n"
        "--- Akhir Transkrip ---\n\n"
        "Ringkasan:"
    )

    try:
        logger.info(f"Requesting summary via DIRECT OpenAI API call (Model: {MODEL_TO_USE}) for transcript length {len(transcript)}...")
        start_time = time.time()
        client = AsyncOpenAI(api_key=api_key)

        response = await client.chat.completions.create(
            model=MODEL_TO_USE,
            messages=[
                {"role": "user", "content": summary_prompt}
            ],
            stream=False
        )

        logger.debug(f"Direct OpenAI API call finished in {time.time() - start_time:.2f}s")

        if response.choices and response.choices[0].message and response.choices[0].message.content:
            summary = response.choices[0].message.content.strip()
            logger.info(f"Direct API summary generated. Length: {len(summary)}")
            if not summary:
                logger.warning("Direct API call returned an empty summary content.")
                return "Model AI tidak dapat menghasilkan ringkasan dari transkrip ini (via direct call)."
            return summary
        else:
            logger.error(f"Unexpected response structure from direct OpenAI call: {response}")
            return "Error: Struktur respons tidak terduga dari API OpenAI."

    except Exception as e:
        logger.error(f"Error during DIRECT OpenAI API summarization: {e}", exc_info=True)
        return f"Error saat membuat ringkasan (direct call): {type(e).__name__}"

# --- Entrypoint Utama Agent ---
async def entrypoint(ctx: JobContext):
    start_entrypoint_time = time.time()
    logger.info(f"Initializing agent for room: {ctx.room.name} (Job ID: {ctx.job.id})")
    assistant: Optional[VoiceAssistant] = None # Deklarasikan di sini agar bisa diakses di handler
    user_id = ctx.room.name
    llm_plugin_for_va: Optional[openai.LLM] = None

    # --- Fungsi Kirim Data ke Klien ---
    async def send_data_to_client(data: str):
        if not ctx.room or not ctx.room.local_participant:
            logger.error("Cannot send data: Room or local participant not available.")
            raise ConnectionError("Room or local participant not available for sending data.")

        logger.debug(f"Attempting to send data via local participant: {data[:100]}...")
        try:
            await ctx.room.local_participant.publish_data(
                payload=data.encode('utf-8')
            )
            logger.info(f"Successfully sent data payload of length {len(data)}.")
        except TypeError as te:
             if "unexpected keyword argument" in str(te):
                 logger.warning(f"publish_data() encountered TypeError ({te}). Retrying without extra arguments.")
                 try:
                     await ctx.room.local_participant.publish_data(payload=data.encode('utf-8'))
                     logger.info(f"Successfully sent data payload (retry without extra args).")
                 except Exception as e_retry:
                     logger.error(f"Failed to publish data even on retry: {e_retry}", exc_info=True)
                     raise e_retry
             else:
                 logger.error(f"Failed to publish data due to TypeError: {te}", exc_info=True)
                 raise te
        except Exception as e:
            logger.error(f"Failed to publish data: {e}", exc_info=True)
            raise

    # --- Handler Asinkronus untuk Data Diterima ---
    async def _handle_data_async(data: DataPacket, participant: Optional[RemoteParticipant]):
        participant_identity = getattr(participant, 'identity', 'Unknown')
        try:
            data_str = data.data.decode('utf-8')
            logger.info(f"Processing data async from {participant_identity}: {data_str[:150]}...")
            json_data = json.loads(data_str)
            msg_type = json_data.get("type")

            if msg_type == "summarize_meeting":
                transcript = json_data.get("transcript")
                logger.info(f"Transcript being sent for summarization:\n---\n{transcript}\n---")
                if transcript:
                    logger.info("Summarization request received. Generating summary async using direct API call...")
                    # Panggil fungsi yang menggunakan API langsung (parameter llm_plugin diabaikan)
                    summary_text = await generate_summary_with_llm(None, transcript) # Kirim None untuk llm_plugin
                    logger.info(f"Summary generated (direct call): '{summary_text[:100]}...'")

                    # Siapkan payload untuk dikirim kembali
                    response_payload = json.dumps({
                        "type": "meeting_summary_result",
                        "summary": summary_text, # Kirim ringkasan asli atau pesan error dari generate_summary
                        "original_transcript": transcript
                    })

                    # --- PERUBAHAN: Jalankan say() dan send_data_to_client() ---
                    speak_task = None
                    if assistant: # Pastikan assistant sudah diinisialisasi
                        # Buat task untuk membacakan ringkasan (atau pesan error)
                        speak_task = asyncio.create_task(
                            assistant.say(summary_text, allow_interruptions=True)
                        )
                        logger.info("Created task for speaking the summary/message.")
                    else:
                        logger.warning("Assistant object not available, cannot speak summary.")

                    # Buat task untuk mengirim data ke klien
                    send_task = asyncio.create_task(
                        send_data_to_client(response_payload)
                    )
                    logger.info("Created task for sending summary result to client.")

                    # Tunggu pengiriman data selesai (penting agar klien mendapat info)
                    try:
                        await send_task
                        logger.info("Successfully sent summary result payload to client.")
                    except Exception as send_e:
                        logger.error(f"Error sending summary result payload: {send_e}", exc_info=True)

                    # Biarkan task speak_task berjalan di background
                    # Jika ingin menunggu selesai (opsional):
                    # if speak_task:
                    #    try:
                    #        await speak_task
                    #    except Exception as speak_e:
                    #        logger.error(f"Error during summary speaking task: {speak_e}", exc_info=True)
                    # -----------------------------------------------------------------

                else:
                    logger.warning("Summarize request received async without transcript.")

        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON data async from {participant_identity}")
        except Exception as e:
            logger.error(f"Error processing data async from {participant_identity}: {e}", exc_info=True)

    # --- Callback Sinkronus untuk Event Data Diterima (tidak berubah) ---
    def _handle_data_sync(data: DataPacket, participant: Optional[RemoteParticipant] = None):
        participant_identity = getattr(participant, 'identity', 'None')
        logger.debug(f"Sync data handler triggered (participant: {participant_identity})")
        if participant and isinstance(participant, RemoteParticipant):
            asyncio.create_task(_handle_data_async(data, participant))
            logger.debug(f"Launched async task to handle data from {participant.identity}")
        elif participant is None:
             try:
                 data_str_check = data.data.decode('utf-8')
                 json_check = json.loads(data_str_check)
                 msg_type_check = json_check.get("type")
                 if msg_type_check == "summarize_meeting":
                     logger.warning("Sync handler: Received 'summarize_meeting' without participant object. Launching async task anyway.")
                     asyncio.create_task(_handle_data_async(data, None))
                 else:
                     logger.warning(f"Sync handler: Received data without participant object (type: {msg_type_check or 'Unknown'}). Ignoring.")
             except Exception as e:
                 logger.error(f"Sync handler: Error checking data type when participant is None: {e}")
        else:
             logger.warning(f"Sync handler: Data received, but not from a RemoteParticipant (type: {type(participant)}, identity: {participant_identity}). Ignoring.")

    # --- Alur Utama Inisialisasi Agent ---
    try:
        logger.info("Connecting to LiveKit room...")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        logger.info(f"Agent connected to room: {ctx.room.name}")

        ctx.room.on("data_received", _handle_data_sync)
        logger.info("Registered synchronous data received handler.")

        logger.info(f"Using user_id for session: {user_id}")

        logger.info("Initializing Assistant Function Context...")
        assistant_fnc = AssistantFnc(
            client=mem0_client,
            send_data_callback=send_data_to_client
        )
        if mem0_client:
            await assistant_fnc.set_user_id(user_id)
        logger.info("Assistant Function Context initialized.")

        # --- Logika Mem0, System Prompt, Greeting (tidak berubah) ---
        retrieved_general_memory_texts = []
        user_name = None
        if mem0_client:
            logger.info(f"Retrieving general context from Mem0 for user '{user_id}'...")
            general_memories = await search_mem0_with_timeout(
                user_id, SEMANTIC_QUERY_GENERAL_STARTUP, limit=5
            )
            if isinstance(general_memories, list):
                retrieved_general_memory_texts = [
                    mem.get('memory') for mem in general_memories if isinstance(mem, dict) and mem.get('memory')
                ]
                logger.info(f"Retrieved {len(retrieved_general_memory_texts)} general context memories.")
                for mem_text in retrieved_general_memory_texts:
                    if "name is" in mem_text.lower():
                        try:
                            parts = mem_text.lower().split("name is", 1)
                            if len(parts) > 1:
                                potential_name = parts[1].strip().split()[0].rstrip('.?!,').capitalize()
                                if potential_name:
                                    user_name = potential_name
                                    logger.info(f"Tentatively extracted user name: {user_name}")
                                    break
                        except Exception as e:
                            logger.warning(f"Error extracting name from memory '{mem_text[:50]}...': {e}")
            else:
                 logger.warning("Failed to retrieve general context or none found.")

        user_name_greeting_hint = f" Nama pengguna mungkin {user_name}." if user_name else " Nama pengguna tidak diketahui."
        general_context_section = ("Konteks dari interaksi sebelumnya:\n" + "\n".join([f"- {mem.strip()}" for mem in retrieved_general_memory_texts])) if retrieved_general_memory_texts else "Tidak ada konteks sebelumnya yang diingat."
        today = datetime.date.today().strftime("%Y-%m-%d")

        system_prompt = (
            "Anda adalah 'Anty', asisten suara yang ramah dan empatik dalam Bahasa Indonesia. "
            "Kepribadian Anda suportif, membantu, dan sedikit informal namun selalu sopan. "
            "Anda memiliki akses ke beberapa alat:\n"
            "- Fungsi memori: `remember_name`, `remember_important_info`, `recall_memories` untuk menyimpan dan mengambil informasi tentang pengguna dan percakapan sebelumnya.\n"
            "- Kontrol perangkat: `set_device_alarm` untuk mengatur alarm (selalu konfirmasi tanggal YYYY-MM-DD, waktu HH:MM, dan pesan terlebih dahulu).\n"
            "- Pencarian internet: `search_internet` untuk menemukan informasi terkini, fakta, atau topik yang tidak Anda ketahui.\n\n"
            f"Tanggal hari ini adalah {today}.\n"
            f"{user_name_greeting_hint}\n\n"
            "--- Konteks Sebelumnya yang Relevan ---\n"
            f"{general_context_section}\n"
            "--- Akhir Konteks ---\n\n"
            "Pedoman:\n"
            "- Gunakan respons singkat dan ringkas, hindari penggunaan tanda baca yang sulit diucapkan.\n"
            "- Jaga agar respons tetap ringkas dan percakapan dalam Bahasa Indonesia.\n"
            "- Bersikaplah empatik dan suportif secara alami.\n"
            "- Gunakan fungsi memori untuk mempersonalisasi percakapan.\n"
            "- Gunakan fungsi perangkat HANYA jika diminta secara eksplisit dan setelah mengonfirmasi semua detail.\n"
            "- **Gunakan fungsi `search_internet` ketika ditanya tentang peristiwa terkini, topik di luar data pelatihan Anda, atau fakta spesifik yang tidak Anda ketahui.**\n"
            "- **PENTING: Sebelum memanggil `search_internet`, SELALU beri tahu pengguna bahwa Anda perlu mencari terlebih dahulu (misalnya, 'Oke, sebentar ya, saya coba cari informasinya dulu.' atau 'Saya perlu mencari itu di internet sebentar.'). Kemudian, panggil fungsinya.**\n"
            "- Jika hasil pencarian memberikan sumber, coba sebutkan secara singkat (misalnya, 'Menurut sumber X...').\n"
            "- Sambil menunggu hasil pencarian berikan informasi tentang informasi yang sedang dicari di internet berdasarkan pengatahuan anda hal ini untuk mencegah kekosongan agar tidak sunyi.\n"
            "- Akui jika Anda tidak tahu sesuatu dan tidak dapat menemukannya.\n"
            "- Saat mengatur alarm, selalu konfirmasi tanggal pasti (format YYYY-MM-DD, selesaikan tanggal relatif seperti 'besok' atau 'Selasa depan' terlebih dahulu), waktu (HH:MM, format 24 jam), dan pesan/label untuk alarm dengan pengguna sebelum memanggil fungsi."
        )
        logger.debug(f"Constructed System Prompt:\n-------\n{system_prompt}\n-------")

        chat_history = llm.ChatContext().append(role="system", text=system_prompt)
        logger.debug("Initial System Prompt prepared and added to chat history.")

        greeting_text = f"Halo{' ' + user_name if user_name else ''}, saya Anty. Ada yang bisa saya bantu hari ini?"
        logger.info(f"Using initial greeting: '{greeting_text}'")

        chat_history.append(role="assistant", text=greeting_text)
        logger.debug("Chat history updated with initial greeting.")

        # --- Inisialisasi LLM & VoiceAssistant ---
        logger.info("Creating LLM plugin instance for VoiceAssistant...")
        # Gunakan model yang sesuai untuk percakapan
        llm_plugin_for_va = openai.LLM(model="gpt-4o-mini") # Atau gpt-4o

        logger.info("Creating VoiceAssistant instance...")
        # Inisialisasi assistant SEBELUM handler data mungkin membutuhkannya
        assistant = VoiceAssistant(
            vad=silero.VAD.load(),
            stt=groq.STT(model="whisper-large-v3-turbo", language="id"),
            llm=llm_plugin_for_va, # VoiceAssistant pakai plugin
            tts=openai.TTS(voice="nova"),
            chat_ctx=chat_history,
            fnc_ctx=assistant_fnc,
            allow_interruptions=True,
        )
        logger.info("VoiceAssistant instance created.")

        # --- Mulai Assistant & Ucapkan Salam ---
        assistant.start(ctx.room)
        logger.info("VoiceAssistant started processing audio and events.")

        try:
            logger.info("Speaking the initial greeting...")
            await assistant.say(greeting_text, allow_interruptions=False)
            logger.info("Initial greeting spoken successfully.")
        except Exception as e:
            logger.error(f"Error speaking initial greeting: {e}", exc_info=True)

        total_setup_time = time.time() - start_entrypoint_time
        logger.info(f"Agent setup and initial greeting complete. Total time: {total_setup_time:.2f} seconds.")

        # --- Jaga entrypoint tetap hidup menggunakan Future ---
        stop_event = asyncio.Future()
        logger.info("Agent running. Awaiting indefinite future to keep alive...")
        try:
            await stop_event
        except asyncio.CancelledError:
            logger.info("Indefinite future cancelled by job context, proceeding to shutdown.")

    except asyncio.CancelledError:
        logger.info("Agent job cancelled by context. Initiating shutdown.")
    except Exception as e:
        logger.error(f"Unhandled error in agent entrypoint: {e}", exc_info=True)
    finally:
        # --- Logika Shutdown ---
        logger.info("Starting agent shutdown sequence (triggered by job end or error)...")
        shutdown_start_time = time.time()

        # Unregister listener
        try:
            if ctx.room and hasattr(ctx.room, 'off'):
                 ctx.room.off("data_received", _handle_data_sync)
                 logger.info("Unregistered data received handler.")
            else:
                 logger.warning("Could not unregister data handler: room object not available or lacks 'off' method during shutdown.")
        except Exception as e:
            logger.warning(f"Could not unregister data handler during shutdown: {e}")

        # Tutup assistant
        if 'assistant' in locals() and assistant:
            logger.info("Closing VoiceAssistant...")
            try:
                await assistant.aclose()
                logger.info("VoiceAssistant closed.")
            except Exception as e:
                logger.error(f"Error closing VoiceAssistant: {e}", exc_info=True)
        else:
            logger.info("VoiceAssistant was not initialized or already closed.")

        # Tutup LLM plugin
        if 'llm_plugin_for_va' in locals() and llm_plugin_for_va and hasattr(llm_plugin_for_va, 'aclose'):
             logger.info("Closing LLM plugin for VoiceAssistant...")
             try:
                 await llm_plugin_for_va.aclose()
                 logger.info("LLM plugin for VoiceAssistant closed.")
             except Exception as e:
                 logger.error(f"Error closing LLM plugin for VoiceAssistant: {e}", exc_info=True)
        else:
             logger.info("LLM Plugin for VoiceAssistant was not initialized or already closed.")

        # Disconnect dari room
        if ctx.room and getattr(ctx.room, 'connection_state', None) == 'connected':
            logger.info("Ensuring disconnection from LiveKit room...")
            try:
                await ctx.disconnect()
                logger.info("Disconnected from LiveKit room via ctx.disconnect().")
            except AttributeError:
                 logger.warning("ctx.disconnect() not found, trying room.disconnect()...")
                 try:
                     await ctx.room.disconnect()
                     logger.info("Disconnected from LiveKit room via room.disconnect().")
                 except Exception as e_room:
                     logger.error(f"Error during final disconnect using room.disconnect(): {e_room}", exc_info=True)
            except Exception as e_ctx:
                logger.error(f"Error during final disconnect using ctx.disconnect(): {e_ctx}", exc_info=True)
        else:
            logger.info("Room already disconnected or not connected during shutdown.")

        logger.info(f"Agent shutdown sequence completed in {time.time() - shutdown_start_time:.2f}s")

# Di bagian akhir file main.py, ubah:
if __name__ == "__main__":
    logger.info("Starting LiveKit Agent worker...")
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
    )

    # Gunakan environment variable untuk menentukan apakah menggunakan SSL
    use_ssl = os.getenv('USE_SSL', 'false').lower() == 'true'

    if use_ssl and os.path.exists('certs/cert.pem') and os.path.exists('certs/key.pem'):
        worker_options.ssl_certfile = 'certs/cert.pem'
        worker_options.ssl_keyfile = 'certs/key.pem'
        logger.info("SSL certificates found and will be used.")
    else:
        logger.info("Running without SSL (will be handled by Contabo/Dokploy).")

    cli.run_app(worker_options)
    logger.info("LiveKit Agent worker finished.")