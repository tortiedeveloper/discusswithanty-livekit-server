import asyncio
import json
import datetime
import logging
import os
from dotenv import load_dotenv
import time
from typing import AsyncGenerator, Optional, Callable, Awaitable

from openai import AsyncOpenAI
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.rtc import DataPacket, DataPacketKind, RemoteParticipant, ConnectionState, Room
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import openai, silero, groq
from livekit import api

from api import AssistantFnc
from mem0 import MemoryClient

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

load_dotenv()
logger.info("Environment variables loaded.")
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    logger.error("FATAL: LIVEKIT_URL, LIVEKIT_API_KEY, dan LIVEKIT_API_SECRET harus diatur.")
    exit(1)
if not os.getenv("PERPLEXITY_API_KEY"):
    logger.warning("PERPLEXITY_API_KEY not found.")
if not os.getenv("OPENAI_API_KEY"):
    logger.error("FATAL: OPENAI_API_KEY not found.")

mem0_client = None
try:
    if api_key := os.getenv("MEM0_API_KEY"):
        logger.info("Initializing Mem0 Client...")
        mem0_client = MemoryClient()
        logger.info("Mem0 Client object created.")
    else:
        logger.warning("MEM0_API_KEY not found.")
except Exception as e:
    logger.error(f"Failed to initialize Mem0 Client: {e}", exc_info=True)

SEMANTIC_QUERY_GENERAL_STARTUP = (
    "Key points, facts, preferences, user's name, user's recent mood, "
    "and user's recent concerns shared in previous conversations"
)
MEM0_SEARCH_TIMEOUT = 15.0
LLM_GREETING_TIMEOUT = 10.0

async def search_mem0_with_timeout(user_id: str, query: str, limit: int = 5):
    if not mem0_client: return None
    try:
        start_time = time.time()
        logger.debug(f"Starting Mem0 search for user '{user_id}' (limit: {limit})")
        search_coro = asyncio.to_thread(mem0_client.search, user_id=user_id, query=query, limit=limit)
        result = await asyncio.wait_for(search_coro, timeout=MEM0_SEARCH_TIMEOUT)
        logger.debug(f"Finished Mem0 search in {time.time() - start_time:.2f}s")
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Mem0 search timed out after {MEM0_SEARCH_TIMEOUT}s")
        return None
    except Exception as e:
        logger.error(f"Error during Mem0 search: {e}", exc_info=True)
        return None

async def generate_summary_with_llm(llm_plugin: Optional[llm.LLM], transcript: str) -> str:
    if not transcript or not transcript.strip(): return "Error: Transkrip kosong."
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key: return "Error: Konfigurasi API Key OpenAI tidak ditemukan."
    MODEL_TO_USE = "gpt-4o"
    summary_prompt = (
        "Anda adalah asisten AI yang bertugas merangkum transkrip berikut dalam Bahasa Indonesia. "
        "Sebutkan topik utama yang dibahas. Jika ada keputusan atau item tindakan yang jelas, sebutkan juga. "
        "Jika tidak ada, cukup rangkum poin utamanya saja secara singkat.\n\n"
        f"Transkrip:\n{transcript}\n\n---\nRingkasan:"
    )
    try:
        logger.info(f"Requesting summary via DIRECT OpenAI API call (Model: {MODEL_TO_USE})...")
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(model=MODEL_TO_USE, messages=[{"role": "user", "content": summary_prompt}], stream=False)
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            summary = response.choices[0].message.content.strip()
            logger.info(f"Direct API summary generated. Length: {len(summary)}")
            return summary or "Model AI tidak dapat menghasilkan ringkasan (via direct call)."
        else:
            logger.error(f"Unexpected response structure from direct OpenAI call: {response}")
            return "Error: Struktur respons tidak terduga dari API OpenAI."
    except Exception as e:
        logger.error(f"Error during DIRECT OpenAI API summarization: {e}", exc_info=True)
        return f"Error saat membuat ringkasan (direct call): {type(e).__name__}"

async def entrypoint(ctx: JobContext):
    start_entrypoint_time = time.time()
    ephemeral_room_name = ctx.room.name
    job_id = ctx.job.id
    logger.info(f"Initializing agent for ephemeral room: {ephemeral_room_name} (Job ID: {job_id})")

    lkapi: Optional[api.LiveKitAPI] = None
    assistant: Optional[VoiceAssistant] = None
    llm_plugin_for_va: Optional[openai.LLM] = None
    assistant_fnc: Optional[AssistantFnc] = None
    persistent_user_id: Optional[str] = None

    try:
        try:
            parts = ephemeral_room_name.split('-')
            if len(parts) == 3 and parts[0] == "usession":
                persistent_user_id = parts[1]
                logger.info(f"Job {job_id}: Successfully extracted persistent user_id from room name: {persistent_user_id}")
            else:
                logger.error(f"Job {job_id}: Could not parse user_id from room name format: {ephemeral_room_name}")
                raise ValueError("Invalid room name format for user_id extraction")
        except Exception as e:
            logger.error(f"Job {job_id}: Error extracting user_id from room name: {e}", exc_info=True)
            raise ValueError("Failed to determine persistent user_id from room name") from e

        if not persistent_user_id:
             logger.critical(f"FATAL: Job {job_id}: persistent_user_id is None after attempting extraction from room name.")
             raise SystemExit("Could not obtain user_id")

        try:
            lkapi = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            logger.info(f"Job {job_id}: LiveKit API Client initialized.")
        except Exception as e:
            logger.error(f"Job {job_id}: Failed to initialize LiveKitAPI client: {e}", exc_info=True)
            lkapi = None

        async def send_data_to_client(data: str):
            if not ctx.room or not ctx.room.local_participant:
                logger.error(f"Job {job_id}: Cannot send data: Room or local participant not available.")
                raise ConnectionError("Room or local participant not available for sending data.")
            logger.debug(f"Job {job_id}: Attempting to send data: {data[:100]}...")
            try:
                await ctx.room.local_participant.publish_data(payload=data.encode('utf-8'))
                logger.info(f"Job {job_id}: Successfully sent data payload length {len(data)}.")
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to publish data: {e}", exc_info=True)
                raise

        async def _handle_data_async(data: DataPacket, participant: Optional[RemoteParticipant]):
            participant_identity = getattr(participant, 'identity', 'Unknown')
            try:
                data_str = data.data.decode('utf-8')
                logger.info(f"Job {job_id}: Processing data async from {participant_identity}: {data_str[:150]}...")
                json_data = json.loads(data_str)
                msg_type = json_data.get("type")

                if msg_type == "summarize_meeting":
                    transcript = json_data.get("transcript")
                    if transcript:
                        logger.info(f"Job {job_id}: Summarization request received. Generating summary async...")
                        summary_text = await generate_summary_with_llm(None, transcript)
                        logger.info(f"Job {job_id}: Summary generated: '{summary_text[:100]}...'")
                        response_payload = json.dumps({"type": "meeting_summary_result", "summary": summary_text, "original_transcript": transcript})
                        speak_task = None
                        if assistant:
                            speak_task = asyncio.create_task(assistant.say(summary_text, allow_interruptions=True))
                        else:
                            logger.warning(f"Job {job_id}: Assistant object not available, cannot speak summary.")
                        send_task = asyncio.create_task(send_data_to_client(response_payload))
                        try:
                            await send_task
                        except Exception as send_e:
                            logger.error(f"Job {job_id}: Error sending summary result: {send_e}", exc_info=True)
                    else:
                        logger.warning(f"Job {job_id}: Summarize request received async without transcript.")

            except json.JSONDecodeError:
                logger.error(f"Job {job_id}: Failed to decode JSON data async from {participant_identity}")
            except Exception as e:
                logger.error(f"Job {job_id}: Error processing data async from {participant_identity}: {e}", exc_info=True)

        def _handle_data_sync(data: DataPacket, participant: Optional[RemoteParticipant] = None):
            participant_identity = getattr(participant, 'identity', 'None')
            logger.debug(f"Job {job_id}: Sync data handler triggered (participant: {participant_identity})")
            if participant and isinstance(participant, RemoteParticipant):
                asyncio.create_task(_handle_data_async(data, participant))
            else:
                logger.warning(f"Job {job_id}: Sync handler: Data received, but not from a RemoteParticipant or participant is None.")

        logger.info(f"Job {job_id}: Connecting to LiveKit room...")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        logger.info(f"Job {job_id}: Agent connected to ephemeral room: {ephemeral_room_name}")

        ctx.room.on("data_received", _handle_data_sync)
        logger.info(f"Job {job_id}: Registered synchronous data received handler.")

        logger.info(f"Job {job_id}: Using persistent user_id for session: {persistent_user_id}")

        logger.info(f"Job {job_id}: Initializing Assistant Function Context...")
        assistant_fnc = AssistantFnc(client=mem0_client, send_data_callback=send_data_to_client)
        if mem0_client and persistent_user_id:
            await assistant_fnc.set_user_id(persistent_user_id)
        logger.info(f"Job {job_id}: Assistant Function Context initialized (without say callback yet).")

        retrieved_general_memory_texts = []
        user_name = None
        if mem0_client and persistent_user_id:
            logger.info(f"Job {job_id}: Retrieving general context from Mem0 for user '{persistent_user_id}'...")
            general_memories = await search_mem0_with_timeout(persistent_user_id, SEMANTIC_QUERY_GENERAL_STARTUP, limit=5)
            if isinstance(general_memories, list):
                retrieved_general_memory_texts = [mem.get('memory') for mem in general_memories if isinstance(mem, dict) and mem.get('memory')]
                logger.info(f"Job {job_id}: Retrieved {len(retrieved_general_memory_texts)} general context memories for user {persistent_user_id}.")
                for mem_text in retrieved_general_memory_texts:
                    if "name is" in mem_text.lower():
                        try:
                            parts = mem_text.lower().split("name is", 1)
                            if len(parts) > 1:
                                potential_name = parts[1].strip().split()[0].rstrip('.?!,').capitalize()
                                if potential_name:
                                    user_name = potential_name
                                    logger.info(f"Job {job_id}: Tentatively extracted user name: {user_name}")
                                    break
                        except Exception as e:
                            logger.warning(f"Job {job_id}: Error extracting name from memory: {e}")
            else:
                logger.warning(f"Job {job_id}: Failed to retrieve general context or none found for user {persistent_user_id}.")

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
            "- **PENTING: Ketika Anda perlu menggunakan `search_internet`:**\n"
            "  3. **Pertama:** Panggil fungsi `search_internet` dengan query yang relevan.\n"
            "  4. **Kedua:** Setelah mendapatkan hasil dari fungsi, sampaikan hasilnya kepada pengguna.\n"
            "- Jika hasil pencarian memberikan sumber, coba sebutkan secara singkat (misalnya, 'Menurut sumber X...').\n"
            "- Akui jika Anda tidak tahu sesuatu dan tidak dapat menemukannya.\n"
            "- Saat mengatur alarm, selalu konfirmasi tanggal pasti (format YYYY-MM-DD, selesaikan tanggal relatif seperti 'besok' atau 'Selasa depan' terlebih dahulu), waktu (HH:MM, format 24 jam), dan pesan/label untuk alarm dengan pengguna sebelum memanggil fungsi."
        )

        chat_history = llm.ChatContext()
        chat_history.append(role="system", text=system_prompt)

        greeting_text = f"Halo{' ' + user_name if user_name else ''}, saya Anty. Ada yang bisa saya bantu?"
        chat_history.append(role="assistant", text=greeting_text)

        logger.info(f"Job {job_id}: Creating LLM plugin instance...")
        llm_plugin_for_va = openai.LLM(model="gpt-4o-mini")
        logger.info(f"Job {job_id}: Loading VAD model...")
        vad_plugin = silero.VAD.load()
        logger.info(f"Job {job_id}: Creating STT plugin instance...")
        stt_plugin = groq.STT(model="whisper-large-v3-turbo", language="id")
        logger.info(f"Job {job_id}: Creating TTS plugin instance...")
        tts_plugin = openai.TTS(voice="nova")

        logger.info(f"Job {job_id}: Creating VoiceAssistant instance...")
        assistant = VoiceAssistant(
            vad=vad_plugin,
            stt=stt_plugin,
            llm=llm_plugin_for_va,
            tts=tts_plugin,
            chat_ctx=chat_history,
            fnc_ctx=assistant_fnc,
            allow_interruptions=True,
        )
        logger.info(f"Job {job_id}: VoiceAssistant instance created.")

        assistant_fnc.set_assistant_say_callback(assistant.say)
        logger.info(f"Job {job_id}: Assistant 'say' callback has been passed to AssistantFnc.")

        assistant.start(ctx.room)
        logger.info(f"Job {job_id}: VoiceAssistant started processing.")
        try:
            logger.info(f"Job {job_id}: Speaking the initial greeting...")
            await assistant.say(greeting_text, allow_interruptions=False)
            logger.info(f"Job {job_id}: Initial greeting spoken.")
        except Exception as e:
            logger.error(f"Job {job_id}: Error speaking initial greeting: {e}", exc_info=True)

        total_setup_time = time.time() - start_entrypoint_time
        logger.info(f"Job {job_id}: Agent setup complete. Total time: {total_setup_time:.2f} seconds.")

        logger.info(f"Job {job_id}: Agent running. Will continue until worker terminates the job.")
        while ctx.room.connection_state == ConnectionState.CONN_CONNECTED:
             await asyncio.sleep(5)
        logger.info(f"Job {job_id}: Room connection state changed to {ctx.room.connection_state}. Agent might exit soon.")

    except ValueError as e:
        logger.error(f"CRITICAL: Could not obtain persistent user_id for Job {job_id}. Agent cannot proceed. Error: {e}")
    except asyncio.CancelledError:
        logger.info(f"Agent job {job_id} cancelled.")
    except Exception as e:
        logger.error(f"Unhandled error in agent entrypoint for Job {job_id}: {e}", exc_info=True)
    finally:
        logger.info(f"Starting shutdown sequence for Job {job_id}...")
        shutdown_start_time = time.time()

        if 'assistant_fnc' in locals() and assistant_fnc:
             logger.info(f"Job {job_id}: AssistantFnc cleanup (if any).")

        try:
            if ctx.room and hasattr(ctx.room, 'off'):
                 ctx.room.off("data_received", _handle_data_sync)
                 logger.info(f"Job {job_id}: Unregistered data received handler.")
            else:
                 logger.warning(f"Job {job_id}: Could not unregister data handler: room object unavailable or lacks 'off' method.")
        except Exception as e:
            logger.warning(f"Job {job_id}: Could not unregister data handler during shutdown: {e}")

        if 'assistant' in locals() and assistant:
            logger.info(f"Job {job_id}: Closing VoiceAssistant...")
            try:
                await assistant.aclose()
                await asyncio.sleep(0.1)
                logger.info(f"Job {job_id}: VoiceAssistant closed.")
            except Exception as e:
                logger.error(f"Job {job_id}: Error closing VoiceAssistant: {e}", exc_info=True)
        else:
            logger.info(f"Job {job_id}: VoiceAssistant not initialized or already closed.")

        if 'llm_plugin_for_va' in locals() and llm_plugin_for_va and hasattr(llm_plugin_for_va, 'aclose'):
             logger.info(f"Job {job_id}: Closing LLM plugin...")
             try:
                 await llm_plugin_for_va.aclose()
             except Exception as e:
                 logger.error(f"Job {job_id}: Error closing LLM plugin: {e}", exc_info=True)
        else:
             logger.info(f"Job {job_id}: LLM Plugin not initialized or already closed.")

        if lkapi:
            logger.info(f"Job {job_id}: Closing LiveKit API client...")
            try:
                await lkapi.aclose()
            except Exception as e:
                logger.error(f"Job {job_id}: Error closing LiveKit API client: {e}", exc_info=True)

        try:
            if ctx.room and hasattr(ctx.room, 'disconnect') and ctx.room.connection_state != ConnectionState.CONN_DISCONNECTED:
                logger.info(f"Job {job_id}: Attempting final room disconnect via room object...")
                await ctx.room.disconnect()
                logger.info(f"Job {job_id}: Room disconnect call completed.")
            else:
                logger.info(f"Job {job_id}: Room already disconnected or room object unavailable for final disconnect.")
        except Exception as e_ctx:
            logger.error(f"Job {job_id}: Error during final disconnect attempt: {e_ctx}", exc_info=True)

        logger.info(f"Agent shutdown sequence for Job {job_id} completed in {time.time() - shutdown_start_time:.2f}s")

if __name__ == "__main__":
    logger.info("Starting LiveKit Agent worker...")
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
    )

    use_ssl = os.getenv('USE_SSL', 'false').lower() == 'true'
    cert_path = 'certs/cert.pem'
    key_path = 'certs/key.pem'
    if use_ssl and os.path.exists(cert_path) and os.path.exists(key_path):
        worker_options.ssl_certfile = cert_path
        worker_options.ssl_keyfile = key_path
        logger.info("SSL certificates found and will be used.")
    else:
        logger.info("Running without SSL.")

    try:
        cli.run_app(worker_options)
    except KeyboardInterrupt:
        logger.info("Worker stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.error(f"Worker failed unexpectedly: {e}", exc_info=True)
    finally:
        logger.info("LiveKit Agent worker finished.")