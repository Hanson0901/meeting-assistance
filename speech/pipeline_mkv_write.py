import subprocess
import signal
import sys

OUTPUT_FILENAME = "output_audio.mkv"

def record_with_arecord_ffmpeg():
    print(f"開始錄音，寫入 {OUTPUT_FILENAME}，Ctrl+C 結束")

    arecord = [
        "arecord",
        "-D", "hw:2,0",
        "-f", "S16_LE",
        "-c", "1",
        "-r", "16000"
    ]

    ffmpeg = [
        "ffmpeg",
        "-y",
        "-f", "s16le",
        "-ar", "16000",
        "-ac", "1",
        "-i", "pipe:0",
        "-c:a", "pcm_s16le",
        "-fflags", "+flush_packets",  # 重要：降低 cache
        "-flush_packets", "1",
        OUTPUT_FILENAME
    ]

    arecord_proc = subprocess.Popen(arecord, stdout=subprocess.PIPE)
    ffmpeg_proc = subprocess.Popen(ffmpeg, stdin=arecord_proc.stdout)

    def shutdown(sig, frame):
        print("\n停止錄音...")
        arecord_proc.terminate()
        ffmpeg_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.pause()

if __name__ == "__main__":
    record_with_arecord_ffmpeg()