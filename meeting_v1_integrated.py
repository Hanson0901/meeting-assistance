#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
會議流程控制器 + 藍牙整合版本
功能:
1) 錄音
2) ASR 轉錄
3) 生成 People/Keypoints/Decisions 報告
4) 提取行動項目
5) 生成摘要
6) 匯出 TXT
7) 藍牙自動傳送結果檔案
8) 藍牙裝置接近監控 (可選)
"""

import os
import sys
import time
import signal
import subprocess
import re
import json
import datetime
import threading
from pathlib import Path
from typing import List, Dict, Optional
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
def _ensure_obexd_running():
    """確保 obexd 服務已啟動 (SessionBus 模式)"""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", "obex"],
            capture_output=True,
            timeout=5
        )
        time.sleep(0.5)  # 給予服務啟動時間
        return True
    except Exception as e:
        print(f"[警告]  無法啟動 obexd: {e}")
        return False


def _get_obex_bus():
    """
    取得 OBEX D-Bus 連接（使用 SessionBus，與 BT_trans_v0_4.py 一致）
    """
    errors = []
    
    # 確保 obexd 已啟動
    _ensure_obexd_running()
    
    # 優先：SessionBus（與 BT_trans_v0_4.py 一致）
    try:
        bus = dbus.SessionBus()
        # 測試連接
        bus.get_object("org.bluez.obex", "/org/bluez/obex")
        print("[OBEX] 使用 SessionBus 連接 OBEX")
        return bus
    except Exception as e:
        errors.append(f"SessionBus failed: {e}")
    
    # 次要：SystemBus（保底）
    try:
        bus = dbus.SystemBus()
        bus.get_object("org.bluez.obex", "/org/bluez/obex")
        print("[OBEX] 使用 SystemBus 連接 OBEX")
        return bus
    except Exception as e:
        errors.append(f"SystemBus failed: {e}")
    
    raise RuntimeError(
        "[OBEX] 找不到 org.bluez.obex（OBEX 服務未啟動或不在同一個 D-Bus）\n"
        + "\n".join(errors)
    )

# --------------------------------------------------
# 將專案根目錄加入 Python 路徑
# --------------------------------------------------
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from print_log_utils import setup_print_logging


# ==========================================
# 藍牙 OBEX 檔案傳送模組
# ==========================================
class ObexPushError(Exception):
    """OBEX 傳送錯誤"""
    pass


class BluetoothFileSender:
    """藍牙檔案傳送器 (基於 BT_trans_v0_4 方式)"""
    
    def __init__(self):
        """初始化藍牙傳送器 - 使用 SessionBus"""
        self.bus = _get_obex_bus()
        self.bluez_bus = dbus.SystemBus()  # 藍牙裝置查詢用 SystemBus
        
    def get_paired_devices(self):
        """取得已配對的藍牙裝置"""
        try:
            manager = dbus.Interface(
                self.bluez_bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager"
            )
            objects = manager.GetManagedObjects()
            
            devices = []
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    props = interfaces["org.bluez.Device1"]
                    if props.get("Paired", False):
                        devices.append({
                            "path": path,
                            "mac": str(props.get("Address", "")),
                            "name": str(props.get("Name", "Unknown")),
                            "connected": bool(props.get("Connected", False))
                        })
            return devices
        except Exception as e:
            raise ObexPushError(f"[藍芽] 無法取得配對裝置: {e}")
    
    def send_file(self, file_path: str, device_mac: str) -> bool:
        """
        透過 OBEX 傳送檔案
        
        Args:
            file_path: 要傳送的檔案路徑
            device_mac: 目標裝置的 MAC 位址
            
        Returns:
            True 表示傳送成功
        """
        try:
            if not os.path.exists(file_path):
                raise ObexPushError(f"[send_file] 檔案不存在: {file_path}")
            
            # 獲取檔案的絕對路徑和大小
            abs_path = os.path.abspath(file_path)
            file_size = os.path.getsize(abs_path)
            file_name = os.path.basename(abs_path)
            
            # 打印傳送檔案的詳細信息
            print(f"  [send_file] 檔案路徑: {abs_path}")
            print(f"  [send_file] 檔案大小: {file_size} bytes ({file_size/1024:.2f} KB)")
            print(f"  [send_file] 檔案名稱: {file_name}")
            
            # 使用 SessionBus 的 OBEX Client
            client = dbus.Interface(
                self.bus.get_object("org.bluez.obex", "/org/bluez/obex"),
                "org.bluez.obex.Client1"
            )
            
            # 建立 OBEX 會話 (OPP = Object Push Profile)
            session_path = client.CreateSession(
                device_mac,
                {"Target": "OPP"}
            )
            print(f"[send_file]  → OBEX 會話建立: {session_path}")
            
            # 建立 ObjectPush 介面並傳送檔案
            obj_push = dbus.Interface(
                self.bus.get_object("org.bluez.obex", session_path),
                "org.bluez.obex.ObjectPush1"
            )
            
            transfer_path, properties = obj_push.SendFile(abs_path)
            print(f"[send_file] 開始傳送: {transfer_path}")
            
            # 等待傳送完成
            props_iface = dbus.Interface(
                self.bus.get_object("org.bluez.obex", transfer_path),
                "org.freedesktop.DBus.Properties"
            )
            
            timeout = 60  # 最多等待 60 秒
            retry_count = 0
            while timeout > 0:
                try:
                    status = str(props_iface.Get("org.bluez.obex.Transfer1", "Status"))
                    transferred = int(props_iface.Get("org.bluez.obex.Transfer1", "Transferred") or 0)
                    total = int(props_iface.Get("org.bluez.obex.Transfer1", "Size") or 0)
                    
                    if total > 0 and transferred > 0:
                        percent = int((transferred / total) * 100)
                        print(f"[send_file] 進度: {percent}% ({transferred}/{total} bytes)")
                    
                    if status == "complete":
                        print(f"  [send_file] 傳送完成")
                        return True
                    elif status == "error":
                        raise ObexPushError("傳送失敗 - 裝置端錯誤")
                    elif status in ["active", "queued", "suspended"]:
                        print(f"[send_file] 狀態: {status}")
                        
                except Exception as e:
                    retry_count += 1
                    if retry_count > 5:
                        print(f"[send_file] 狀態查詢失敗: {e}")
                
                time.sleep(0.5)
                timeout -= 0.5
            
            raise ObexPushError("[send_file] 傳送逾時 (超過 60 秒)")
            
        except dbus.exceptions.DBusException as e:
            raise ObexPushError(f"[send_file] D-Bus 錯誤: {e}")
        except ObexPushError:
            raise
        except Exception as e:
            raise ObexPushError(f"[send_file] 未預期的錯誤: {e}")
    
    def auto_send_to_first_paired(self, files: List[str]) -> tuple:
        """
        自動傳送檔案到第一個已配對的裝置 (無需手動選擇)
        
        Args:
            files: 要傳送的檔案列表
            
        Returns:
            (mac, name) 成功傳送的裝置資訊
        """
        devices = self.get_paired_devices()
        
        if not devices:
            raise ObexPushError("[send_to_paired] 沒有已配對的藍牙裝置")
        
        # 優先選擇已連線的裝置
        target = None
        for dev in devices:
            if dev["connected"]:
                target = dev
                break
        
        if not target:
            target = devices[0]
        
        print(f"[send_to_paired] 藍牙傳送目標: {target['name']} ({target['mac']})")
        
        success_count = 0
        failed_files = []
        
        for file_path in files:
            if not os.path.exists(file_path):
                print(f"[send_to_paired] 檔案不存在: {file_path}")
                failed_files.append(os.path.basename(file_path))
                continue
            
            file_name = os.path.basename(file_path)
            print(f"[send_to_paired] 傳送檔案: {file_name}")
            
            try:
                self.send_file(file_path, target["mac"])
                success_count += 1
                time.sleep(0.5)  # 檔案間隔
            except ObexPushError as e:
                print(f"[send_to_paired] 傳送失敗: {e}")
                failed_files.append(file_name)
        
        # 傳送摘要
        print(f"\n{'='*60}")
        print(f"[send_to_paired] 傳送統計:")
        print(f"[send_to_paired] 成功: {success_count}/{len(files)} 個檔案")
        if failed_files:
            print(f"[send_to_paired] 失敗: {', '.join(failed_files)}")
        print(f"{'='*60}\n")
        
        if success_count == 0:
            raise ObexPushError("[send_to_paired] 所有檔案傳送失敗")
        
        return target["mac"], target["name"]
    


# ==========================================
# 藍牙接近監控模組 (選用)
# ==========================================
class BluetoothProximityMonitor:
    """藍牙裝置接近監控"""
    
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.monitoring = False
        self.thread = None
        
    def check_device_nearby(self, mac: str, threshold_rssi: int = -70) -> bool:
        """
        檢查裝置是否在附近
        
        Args:
            mac: 裝置 MAC 位址
            threshold_rssi: RSSI 門檻值 (dBm)
            
        Returns:
            True 表示裝置在附近
        """
        try:
            # 使用 l2ping 檢測
            result = subprocess.run(
                ["l2ping", "-c", "1", "-t", "2", mac],
                capture_output=True,
                text=True,
                timeout=3
            )
            return result.returncode == 0
        except:
            return False
    
    def start_monitoring(self, devices: List[Dict], callback=None):
        """
        開始監控裝置
        
        Args:
            devices: 要監控的裝置列表 [{"mac": "...", "name": "..."}]
            callback: 當裝置狀態改變時的回調函數 callback(mac, name, is_nearby)
        """
        if self.monitoring:
            return
        
        self.monitoring = True
        
        def monitor_loop():
            device_states = {d["mac"]: False for d in devices}
            
            while self.monitoring:
                for device in devices:
                    mac = device["mac"]
                    name = device.get("name", mac)
                    
                    is_nearby = self.check_device_nearby(mac)
                    
                    # 狀態改變時觸發回調
                    if is_nearby != device_states[mac]:
                        device_states[mac] = is_nearby
                        if callback:
                            callback(mac, name, is_nearby)
                
                time.sleep(5)  # 每 5 秒檢查一次
        
        self.thread = threading.Thread(target=monitor_loop, daemon=True)
        self.thread.start()
    
    def stop_monitoring(self):
        """停止監控"""
        self.monitoring = False
        if self.thread:
            self.thread.join(timeout=2)


# ==========================================
# 會議工作流程控制器
# ==========================================
class MeetingWorkflow:
    """會議工作流程控制器 (整合藍牙功能)"""

    def __init__(
        self,
        audio_device="hw:2,0",
        output_dir=".",
        output_prefix="output",
        model_path="/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf",
        interval_minutes=5,
        overlap_seconds=60,
        enable_recording=True,
        enable_bluetooth=True,
        enable_proximity_monitor=False,
        enable_write_output=True,
        include_actions_and_summary_files=True,
        include_decisions_in_final_txt=True,
    ):
        self.audio_device = audio_device
        self.output_dir = output_dir
        self.output_prefix = output_prefix
        self.model_path = model_path
        self.interval_minutes = interval_minutes
        self.overlap_seconds = overlap_seconds
        self.enable_recording = enable_recording

        self.audio_file = os.path.join(output_dir, f"{output_prefix}_audio.mkv")
        self.recording_flag_file = os.path.join(output_dir, f"{output_prefix}.recording")
        self.actions_file = os.path.join(output_dir, f"{output_prefix}_actions.txt")
        self.summary_file = os.path.join(output_dir, f"{output_prefix}_summary.txt")
        self.txt_file = os.path.join(output_dir, f"{output_prefix}_meeting_summary.txt")
        
        self.dump_cache_in_txt = False
        self.enable_bluetooth = enable_bluetooth
        self.enable_proximity_monitor = enable_proximity_monitor
        self.enable_write_output = enable_write_output
        self.include_actions_and_summary_files = include_actions_and_summary_files
        self.include_decisions_in_final_txt = include_decisions_in_final_txt

        os.makedirs(output_dir, exist_ok=True)
        default_log_file = os.path.join(
            output_dir,
            f"{output_prefix}_run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        )
        self.log_file = setup_print_logging(
            default_log_path=default_log_file,
            process_name="meeting_v1_integrated",
        )
        self.is_recording = False
        self.cache: Dict[str, object] = {}
        
        # 計時功能
        self.step_times = {}  # 儲存每個 step 的耗時
        
        # 藍牙模組
        if self.enable_bluetooth:
            try:
                self.bt_sender = BluetoothFileSender()
                print("[MeetingWorkflow][init] 藍牙傳送模組已啟用")
            except Exception as e:
                print(f"  藍牙傳送模組啟動失敗: {e}")
                self.enable_bluetooth = False
        
        if self.enable_proximity_monitor:
            try:
                self.bt_monitor = BluetoothProximityMonitor()
                print("[MeetingWorkflow][init] 藍牙監控模組已啟用")
            except Exception as e:
                print(f"[MeetingWorkflow][init]  藍牙監控模組啟動失敗: {e}")
                self.enable_proximity_monitor = False

    # --------------------------------------------------
    def _print_banner(self, text: str):
        print("\n" + "=" * 60)
        print(f"  {text}")
        print("=" * 60 + "\n")

    def _list_srt_files(self) -> List[Path]:
        pattern = f"{self.output_prefix}_*.srt"
        return sorted(Path(self.output_dir).glob(pattern))

    # ------------------------
    # SRT -> 純文字
    # ------------------------
    def _srt_to_text(self, srt_path: str) -> str:
        lines_out = []
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.isdigit() or "-->" in line:
                    continue
                lines_out.append(line)
        return "\n".join(lines_out)

    # ------------------------
    # 清理輸出文字
    # ------------------------
    @staticmethod
    def _clean_thought_tags(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text)
        if "<think>" in text:
            text = text.split("<think>")[0]
        text = text.replace("</think>", "")

        patterns = [
            r"^好的.*",
            r"^根據.*",
            r"^Here is.*",
            r"^Sure,.*",
            r"^以下是.*",
            r"^Okay,.*",
        ]
        for p in patterns:
            text = re.sub(p, "", text, flags=re.MULTILINE)

        return text.strip()

    @staticmethod
    def _parse_time_to_seconds(time_str: str) -> Optional[float]:
        time_str = time_str.strip()
        try:
            if ":" in time_str:
                parts = time_str.replace(",", ".").split(":")
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            return float(time_str)
        except Exception:
            return None

    def _parse_srt_brute_force(self, file_path: str) -> List[Dict]:
        encodings = ["utf-8", "utf-8-sig", "cp950", "gbk"]
        lines = []
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    lines = f.readlines()
                print(f"[MeetingWorkflow][parse_srt_brute_force] 使用編碼 {enc} 讀取成功,共 {len(lines)} 行")
                break
            except:
                continue

        if not lines:
            return []

        all_subtitles = []
        current_start = None
        current_text = []

        for line in lines:
            line = line.strip()

            if "-->" in line:
                if current_start is not None and current_text:
                    all_subtitles.append({"start": current_start, "text": " ".join(current_text)})
                    current_text = []
                try:
                    parts = line.split("-->")
                    t = self._parse_time_to_seconds(parts[0])
                    current_start = t if t is not None else None
                except:
                    current_start = None
                continue

            if line.isdigit() or not line:
                continue

            if current_start is not None:
                current_text.append(line)

        if current_start is not None and current_text:
            all_subtitles.append({"start": current_start, "text": " ".join(current_text)})

        return all_subtitles

    def _split_subtitles_to_segments(self, subtitles: List[Dict]) -> List[str]:
        if not subtitles:
            return []

        subtitles.sort(key=lambda x: x["start"])
        interval_sec = self.interval_minutes * 60

        min_time = subtitles[0]["start"]
        max_time = subtitles[-1]["start"]

        start_chunk_idx = int(min_time // interval_sec)
        end_chunk_idx = int(max_time // interval_sec)

        print(f"[MeetingWorkflow][split_subtitles_to_segments] 偵測 SRT 時間範圍: {int(min_time)}秒 ~ {int(max_time)}秒")
        segments = []

        for i in range(start_chunk_idx, end_chunk_idx + 1):
            chunk_start = i * interval_sec
            chunk_end = (i + 1) * interval_sec + self.overlap_seconds

            current_text_list = []
            for sub in subtitles:
                if chunk_start <= sub["start"] < chunk_end:
                    current_text_list.append(sub["text"])

            if current_text_list:
                label = f"{i*self.interval_minutes:02d}:00 - {(i+1)*self.interval_minutes:02d}:00"
                segments.append(f"[MeetingWorkflow][split_subtitles_to_segments] 【時間段 {label}】\n" + "\n".join(current_text_list))

        return segments

    # ------------------------
    # step1: 錄音
    # ------------------------
    def step1_record(self) -> bool:
        step_start = time.perf_counter()
        self._print_banner("步驟 1/6: 開始錄音")
        print(f"[MeetingWorkflow][step1_record] 音訊設備: {self.audio_device}")
        print(f"[MeetingWorkflow][step1_record] 輸出檔案: {self.audio_file}")
        print("[MeetingWorkflow][step1_record]  按 Ctrl+C 結束錄音\n")

        arecord_cmd = [
            "arecord",
            "-D", self.audio_device,
            "-f", "S16_LE",
            "-c", "1",
            "-r", "48000",     # 這裡改 48000
        ]

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f", "s16le",
            "-ar", "48000",    # 這裡也改 48000，跟 arecord 保持一致
            "-ac", "1",
            "-i", "pipe:0",
            "-c:a", "pcm_s16le",
            "-fflags", "+flush_packets",
            "-flush_packets", "1",
            self.audio_file,
        ]

        arecord_proc = None
        ffmpeg_proc = None
        old_handler = signal.getsignal(signal.SIGINT)

        def _on_sigint(sig, frame):
            if self.is_recording:
                print("[MeetingWorkflow][step1_record][on_sigint] 正在停止錄音...")
                self.is_recording = False

        try:
            with open(self.recording_flag_file, "w", encoding="utf-8") as flag_f:
                flag_f.write(str(os.getpid()))

            arecord_proc = subprocess.Popen(
                arecord_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=arecord_proc.stdout,
                stderr=subprocess.DEVNULL,
            )

            self.is_recording = True
            signal.signal(signal.SIGINT, _on_sigint)

            print("[MeetingWorkflow][step1_record] 錄音進行中...\n")
            while self.is_recording:
                time.sleep(0.2)

        finally:
            signal.signal(signal.SIGINT, old_handler)

            for p in (arecord_proc, ffmpeg_proc):
                try:
                    if p and p.poll() is None:
                        p.terminate()
                except:
                    pass

            for p in (arecord_proc, ffmpeg_proc):
                try:
                    if p and p.poll() is None:
                        p.wait(timeout=2)
                except:
                    try:
                        p.kill()
                    except:
                        pass

            try:
                if os.path.exists(self.recording_flag_file):
                    os.remove(self.recording_flag_file)
            except Exception as e:
                print(f"[MeetingWorkflow][step1_record] 清除錄音旗標失敗: {e}")

            self.step_times['step1'] = time.perf_counter() - step_start
            print(f"[MeetingWorkflow][step1_record] step1 耗時: {self.step_times['step1']:.2f} 秒\n")

        if os.path.exists(self.audio_file):
            print("[MeetingWorkflow][step1_record] 錄音已停止")
            print(f"[MeetingWorkflow][step1_record] 音訊檔案已儲存: {self.audio_file}")
            return True

        print("[MeetingWorkflow][step1_record] 找不到錄音輸出檔\n")
        return False

    # ------------------------
    # step2: ASR
    # ------------------------
    def step2_transcribe(self) -> bool:
        step_start = time.perf_counter()
        self._print_banner("步驟 2/6: 語音轉文字 (ASR)")
        print(f"[MeetingWorkflow][step2_transcribe] 讀取音訊: {self.audio_file}")
        print("[MeetingWorkflow][step2_transcribe]  按 Ctrl+C 可提前結束轉錄\n")

        try:
            if not os.path.exists(self.audio_file):
                print("[MeetingWorkflow][step2_transcribe] 音訊檔不存在\n")
                return False

            conda_python = "/home/cgu-csie/miniconda3/bin/python3"
            asr_script = os.path.join(project_root, "speech", "run_asr_conda.py")

            cmd = [
                "sudo", "-u", "cgu-csie",         # 重要：用你的帳號跑 conda，不要用 root
                conda_python,
                asr_script,
                "--audio", self.audio_file,
                "--outdir", self.output_dir,
                "--prefix", self.output_prefix,
                "--alpha", "0.0",
                "--overlap", "5.0",
                "--verbose",
            ]

            if self.enable_recording:
                cmd.extend(["--recording-flag", self.recording_flag_file])

            print("[MeetingWorkflow][step2_transcribe] 使用 conda Python 執行 ASR：")
            print("   " + " ".join(cmd) + "\n")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
            if self.log_file:
                env["MEETING_LOG_FILE"] = self.log_file

            try:
                subprocess.run(cmd, check=True, cwd=str(project_root), env=env)
            except subprocess.CalledProcessError as e:
                print(f"[MeetingWorkflow][step2_transcribe] ASR 失敗: {e}\n")
                return False

            print("[MeetingWorkflow][step2_transcribe] ASR 轉錄完成")
            return True
        finally:
            self.step_times['step2'] = time.perf_counter() - step_start
            print(f"[MeetingWorkflow][step2_transcribe] step2 耗時: {self.step_times['step2']:.2f} 秒\n")


    # ------------------------
    # step3: People/Keypoints/Decisions
    # ------------------------
    def step3_run_pkd_reports(self) -> bool:
        step_start = time.perf_counter()
        self._print_banner("步驟 3/6: 生成 People/Keypoints/Decisions 報告 (conda worker)")

        try:
            if not os.path.exists(self.model_path):
                print(f"[MeetingWorkflow][step3_run_pkd_reports] 找不到模型: {self.model_path}\n")
                return False

            conda_python = "/home/cgu-csie/miniconda3/bin/python3"
            worker = os.path.join(project_root, "run_pkd_conda.py")
            out_json = os.path.join(self.output_dir, f"{self.output_prefix}_pkd_cache.json")

            cmd = [
                "sudo", "-u", "cgu-csie",
                conda_python, worker,
                "--output-dir", self.output_dir,
                "--output-prefix", self.output_prefix,
                "--model-path", self.model_path,
                "--interval-minutes", str(self.interval_minutes),
                "--overlap-seconds", str(self.overlap_seconds),
            ]

            print("[MeetingWorkflow][step3_run_pkd_reports] 使用 conda Python 執行 PKD：")
            print("   " + " ".join(cmd) + "\n")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
            if self.log_file:
                env["MEETING_LOG_FILE"] = self.log_file

            try:
                subprocess.run(cmd, check=True, cwd=str(project_root), env=env)
            except subprocess.CalledProcessError as e:
                print(f"[MeetingWorkflow][step3_run_pkd_reports] PKD 失敗: {e}\n")
                return False

            # 讀回結果
            import json
            if not os.path.exists(out_json):
                print(f"[MeetingWorkflow][step3_run_pkd_reports] 找不到 PKD 輸出: {out_json}\n")
                return False
            with open(out_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cache["people"] = data.get("people", "").strip() or "(無)"
            self.cache["keypoints"] = data.get("keypoints", "").strip() or "(無)"
            self.cache["decisions"] = data.get("decisions", "").strip() or "(無)"

            # ✅ 新增：寫入 cache JSON 供 step5 使用
            cache_json = os.path.join(self.output_dir, f"{self.output_prefix}_cache.json")
            cache_data = {
                "people": self.cache["people"],
                "keypoints": self.cache["keypoints"],
                "decisions": self.cache["decisions"],
            }
            with open(cache_json, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"[MeetingWorkflow][step3_run_pkd_reports] cache 已寫入: {cache_json}\n")
            print(f"[MeetingWorkflow][step3_run_pkd_reports] step3 完成：P/K/D 已寫入 cache")
            return True
        except Exception as e:
            print(f"[MeetingWorkflow][step3_run_pkd_reports] 讀取 PKD 結果失敗: {e}\n")
            return False
        finally:
            self.step_times['step3'] = time.perf_counter() - step_start
            print(f"[MeetingWorkflow][step3_run_pkd_reports] step3 耗時: {self.step_times['step3']:.2f} 秒\n")

    # ------------------------
    # step4: Actions
    # ------------------------
    def step4_extract_actions(self) -> bool:
        step_start = time.perf_counter()
        self._print_banner("步驟 4/6: 提取行動項目 (conda worker)")

        try:
            conda_python = "/home/cgu-csie/miniconda3/bin/python3"
            worker = os.path.join(project_root, "run_actions_conda.py")
            out_json = os.path.join(self.output_dir, f"{self.output_prefix}_actions_cache.json")
            cmd = [
                "sudo", "-u", "cgu-csie",
                conda_python, worker,
                "--output-dir", self.output_dir,
                "--output-prefix", self.output_prefix,
            ]

            print("[MeetingWorkflow][step4_extract_actions] 使用 conda Python 執行 Actions：")
            print("[MeetingWorkflow][step4_extract_actions]   " + " ".join(cmd) + "\n")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
            if self.log_file:
                env["MEETING_LOG_FILE"] = self.log_file

            try:
                subprocess.run(cmd, check=True, cwd=str(project_root), env=env)
            except subprocess.CalledProcessError as e:
                print(f"[MeetingWorkflow][step4_extract_actions] Actions 失敗: {e}\n")
                return False

            # 讀回結果
            import json
            if not os.path.exists(out_json):
                print(f"[MeetingWorkflow][step4_extract_actions] 找不到 Actions 輸出: {out_json}\n")
                return False
            with open(out_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.cache["segments"] = data.get("segments", [])
            self.cache["actions_lines"] = data.get("actions_lines", [])
            self.cache["actions_text"] = data.get("actions_text", "本段無具體行動項目")

            # 同步輸出文字檔（系統端負責 I/O）
            with open(self.actions_file, "w", encoding="utf-8") as f:
                f.write("會議行動項目清單\n" + "="*60 + "\n\n")
                if self.cache["actions_lines"]:
                    for i, line in enumerate(self.cache["actions_lines"], 1):
                        f.write(f"{i}. {line}\n")
                else:
                    f.write("本次會議無具體行動項目\n")

            # 新增：更新 cache JSON，加入 actions_text
            cache_json = os.path.join(self.output_dir, f"{self.output_prefix}_cache.json")
            import json
            # 讀取既有的 cache（包含 P/K/D）
            if os.path.exists(cache_json):
                with open(cache_json, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            else:
                cache_data = {}
        
            # 加入 actions_text
            cache_data["actions_text"] = self.cache["actions_text"]
        
            with open(cache_json, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"[MeetingWorkflow][step4_extract_actions] cache 已更新: {cache_json}\n")
            print(f"[MeetingWorkflow][step4_extract_actions] 行動項目已輸出: {self.actions_file}")
            return True
        except Exception as e:
            print(f"[MeetingWorkflow][step4_extract_actions] 讀取 Actions 結果失敗: {e}\n")
            return False
        finally:
            self.step_times['step4'] = time.perf_counter() - step_start
            print(f"[MeetingWorkflow][step4_extract_actions] step4 耗時: {self.step_times['step4']:.2f} 秒\n")
       


    # ------------------------
    # step5: Summary
    # ------------------------
    def step5_generate_summary(self) -> bool:
        step_start = time.perf_counter()
        self._print_banner("步驟 5/6: 生成會議摘要 (conda worker)")

        try:
            conda_python = "/home/cgu-csie/miniconda3/bin/python3"
            worker = os.path.join(project_root, "run_summary_conda.py")
            out_json = os.path.join(
                self.output_dir, f"{self.output_prefix}_summary_cache.json"
            )

            cmd = [
                "sudo", "-u", "cgu-csie",
                conda_python, worker,
                "--output-dir", self.output_dir,
                "--output-prefix", self.output_prefix,
            ]
            print("[MeetingWorkflow][step5_generate_summary] 使用 conda Python 執行 Summary：")
            print("[MeetingWorkflow][step5_generate_summary]   " + " ".join(cmd) + "\n")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
            if self.log_file:
                env["MEETING_LOG_FILE"] = self.log_file

            try:
                subprocess.run(cmd, check=True, cwd=str(project_root), env=env)
            except subprocess.CalledProcessError as e:
                print(f"[MeetingWorkflow][step5_generate_summary] Summary 失敗: {e}\n")
                return False

            import json
            if not os.path.exists(out_json):
                print(f"[MeetingWorkflow][step5_generate_summary] 找不到 Summary 輸出: {out_json}\n")
                return False

            with open(out_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 若 summary 為 null, 或是空字串，或包含『無法生成摘要』字樣，視為沒有摘要
            raw_summary = data.get("summary", None)
            raw_title = data.get("title", None)
            
            # 處理 title
            if raw_title is None:
                self.cache["title"] = ""
            else:
                t = str(raw_title).strip()
                if not t or "無法生成標題" in t:
                    self.cache["title"] = ""
                else:
                    self.cache["title"] = t
                    
            if raw_summary is None:
                self.cache["summary"] = ""
            else:
                s = str(raw_summary).strip()
                if not s or "無法生成摘要" in s:
                    self.cache["summary"] = ""
                else:
                    self.cache["summary"] = s

            # 只有在有摘要內容時才輸出 summary.txt
            summary_txt = os.path.join(
                self.output_dir, f"{self.output_prefix}_summary.txt"
            )
            if self.cache["summary"] or self.cache["title"]:
                with open(summary_txt, "w", encoding="utf-8") as f:
                    if self.cache["title"]:
                        f.write(self.cache["title"] + "\n")
                        f.write("=" * 60 + "\n\n")
                    else:
                        f.write("會議摘要\n")
                        f.write("=" * 60 + "\n\n")
                        
                    f.write(self.cache["summary"] + "\n")

                print(f"[MeetingWorkflow][step5_generate_summary] 摘要已輸出: {summary_txt}\n")
            else:
                print(f"[MeetingWorkflow][step5_generate_summary] Summary 為空或 null，跳過輸出 summary.txt\n")

        except Exception as e:
            print(f"[MeetingWorkflow][step5_generate_summary] 讀取 Summary 結果失敗: {e}\n")
            return False
        finally:
            self.step_times['step5'] = time.perf_counter() - step_start
            print(f"[MeetingWorkflow][step5_generate_summary] step5 耗時: {self.step_times['step5']:.2f} 秒\n")

        return True
    # ------------------------
    # step6: Export TXT + Bluetooth
    # ------------------------
    def step6_export_txt(self) -> bool:
        step_start = time.perf_counter()
        self._print_banner("步驟 6/6: 匯出 TXT + 藍牙傳送")
        try:
            # 檢查是否啟用寫檔功能
            if not self.enable_write_output:
                print(f"[MeetingWorkflow][step6_export_txt]  寫檔功能已禁用，跳過 step6\n")
                return True

            def _write_section(f, title: str, content: str):
                content = (content or "").strip()
                if not content:
                    return
                f.write(f"\n{title}\n" + "="*60 + "\n")
                f.write(content)
                f.write("\n")

            def _write_list(f, title: str, items):
                f.write(f"\n{title}\n" + "="*60 + "\n")
                if not items:
                    f.write("(空)\n")
                    return
                for i, it in enumerate(items, 1):
                    f.write(f"{i}. {it}\n")

            try:
                with open(self.txt_file, "w", encoding="utf-8") as f:
                    f.write("會議摘要報告(TXT)\n" + "="*60 + "\n")
                    f.write(f"產生時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    
                    _write_section(f, "會議主題(Title)", self.cache.get("title", ""))
                    _write_section(f, "整體摘要(Summary)", self.cache.get("summary", ""))
                    _write_section(f, "與會人員(People)", self.cache.get("people", ""))
                    _write_section(f, "會議重點(Keypoints)", self.cache.get("keypoints", ""))
                    if self.include_decisions_in_final_txt:
                        _write_section(f, "決策事項(Decisions)", self.cache.get("decisions", ""))
                    _write_list(f, "行動項目(Actions)", self.cache.get("actions_lines", []))

            except Exception as e:
                print(f"[MeetingWorkflow][step6_export_txt] TXT 產生失敗: {e}")
                return False

            print(f"[MeetingWorkflow][step6_export_txt] TXT 已輸出: {self.txt_file}\n")

            # =========================
            # ★ 藍牙傳送結果檔案（基於 BT_trans_v0_4 方式）
            # =========================
            if self.enable_bluetooth:
                try:
                    if self.include_actions_and_summary_files:
                        files_to_send = [
                            self.txt_file,
                            self.actions_file,
                            self.summary_file,
                        ]
                    else:
                        files_to_send = [self.txt_file]

                    mac, name = self.bt_sender.auto_send_to_first_paired(files_to_send)
                    print(f"[MeetingWorkflow][step6_export_txt] 藍牙傳送完成: {name} ({mac})\n")

                except ObexPushError as e:
                    print(f"[MeetingWorkflow][step6_export_txt] 藍牙傳送失敗: {e}")
                    print("[MeetingWorkflow][step6_export_txt]    檢查項目:")
                    print("[MeetingWorkflow][step6_export_txt]      確保藍牙裝置已配對且在範圍內")
                    print("[MeetingWorkflow][step6_export_txt]      執行: systemctl --user status obex")
                    print("[MeetingWorkflow][step6_export_txt]      執行: systemctl --user restart obex\n")
                except Exception as e:
                    print(f"[MeetingWorkflow][step6_export_txt] 藍牙未預期錯誤: {e}\n")
            else:
                print("[MeetingWorkflow][step6_export_txt]  藍牙傳送已禁用\n")

            return True
        finally:
            self.step_times['step6'] = time.perf_counter() - step_start
            print(f"[MeetingWorkflow][step6_export_txt] step6 耗時: {self.step_times['step6']:.2f} 秒\n")

    # ------------------------
    # 主流程
    # ------------------------
    def run(self) -> bool:
        workflow_start = time.perf_counter()
        self._print_banner(" 會議工作流程控制器 (整合藍牙版)")

        # 啟動藍牙監控 (選用)
        if self.enable_proximity_monitor:
            try:
                devices = self.bt_sender.get_paired_devices()
                if devices:
                    def on_device_change(mac, name, is_nearby):
                        status = " 進入範圍" if is_nearby else " 離開範圍"
                        print(f"\n[MeetingWorkflow][run] {name}: {status}")
                    
                    monitor_devices = [{"mac": d["mac"], "name": d["name"]} for d in devices[:3]]
                    self.bt_monitor.start_monitoring(monitor_devices, callback=on_device_change)
                    print(f"[MeetingWorkflow][run] {len(monitor_devices)} 個裝置\n")
            except Exception as e:
                print(f"[MeetingWorkflow][run]  藍牙監控啟動失敗: {e}\n")

        # 執行主要流程
        if self.enable_recording:
            if not self.step1_record():
                return False
        else:
            print("[MeetingWorkflow][run]  錄音步驟已停用，直接使用既有音訊檔\n")
        if not self.step2_transcribe():
            return False
        if not self.step3_run_pkd_reports():
            return False
        if not self.step4_extract_actions():
            return False
        if not self.step5_generate_summary():
            return False
        if not self.step6_export_txt():
            return False

        # 停止藍牙監控
        if self.enable_proximity_monitor:
            try:
                self.bt_monitor.stop_monitoring()
                print("[MeetingWorkflow][run] 藍牙監控已停止\n")
            except Exception as e:
                print(f"[MeetingWorkflow][run]  停止監控失敗: {e}\n")

        self._print_banner(" 工作流程完成")
        
        # 計時統計
        total_time = time.perf_counter() - workflow_start
        print("[MeetingWorkflow][run]  計時統計:")
        for i in range(1, 7):
            step_key = f'step{i}'
            if step_key in self.step_times:
                print(f"[MeetingWorkflow][run]  step{i}: {self.step_times[step_key]:.2f} 秒")
        print(f"[MeetingWorkflow][run]  總耗時: {total_time:.2f} 秒")
        print("[MeetingWorkflow][run] 全流程結束\n")
        return True


# ==========================================
# step3 完整實作 (extract 函數)
# ==========================================
def extract_raw_people(extractor, text: str) -> str:
    """提取人物"""
    prompt = f"""<|im_start|>system
你是一個精準的資料提取程式。請從會議記錄片段中識別出現的人物。

要則:
1. **嚴禁**輸出 <think> 思考過程,直接給出結果。
2. 若無人名輸出 "無"。
3. **過濾**:若只有職稱(如部長、主席)沒有名字,請忽略。
4. 格式:- [姓名]:[職位/角色]
<|im_end|>
<|im_start|>user
會議片段:
{text[:3500]}

請列出人物:
<|im_end|>
<|im_start|>assistant
"""
    try:
        out = extractor.model(
            prompt,
            max_tokens=600,
            temperature=0.1,
            repeat_penalty=1.1,
            stop=["<|im_end|>", "###"],
        )
        return MeetingWorkflow._clean_thought_tags(out["choices"][0]["text"])
    except Exception:
        return ""


def generate_final_people_summary(extractor, raw_list: List[str]) -> str:
    """生成最終人物摘要"""
    clean_list = [MeetingWorkflow._clean_thought_tags(r) for r in raw_list]
    combined_text = "\n".join(clean_list)
    prompt = f"""<|im_start|>system
你是一位專業秘書。請整理「與會人員名單」。

要則:
1. **去重合併**:整合同一人的資訊。
2. **結構化**:使用 Markdown 條列式。
3. **嚴禁**輸出 `<think>` 標籤。
4. **繁體中文**。

輸出格式:
### [姓名]
- 職位/角色:[說明]

<|im_end|>
<|im_start|>user
原始資料:
{combined_text}

請整理最終名單:
<|im_end|>
<|im_start|>assistant
"""
    try:
        out = extractor.model(
            prompt,
            max_tokens=1500,
            temperature=0.2,
            repeat_penalty=1.1,
            stop=["<|im_end|>"],
        )
        return MeetingWorkflow._clean_thought_tags(out["choices"][0]["text"])
    except Exception:
        return "[generate_people_summary] 總結生成失敗"


def extract_raw_keypoints(extractor, text: str) -> str:
    """提取關鍵重點"""
    prompt = f"""<|im_start|>system
你是一個專業的會議記錄分析師。請從這段會議記錄中提取「核心要點」。

嚴格要則:
1. **禁止**輸出 <think> 標籤或思考過程。
2. **禁止**輸出任何開場白。
3. 格式:- [關鍵詞]:具體說明
<|im_end|>
<|im_start|>user
會議片段:
{text[:3500]}

請提取重點:
<|im_end|>
<|im_start|>assistant
"""
    try:
        out = extractor.model(
            prompt,
            max_tokens=600,
            temperature=0.1,
            repeat_penalty=1.1,
            stop=["<|im_end|>", "###"],
        )
        return MeetingWorkflow._clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return ""


def generate_final_keypoints_summary(extractor, raw_list: List[str]) -> str:
    """生成最終重點摘要"""
    combined_text = "\n".join(raw_list)
    prompt = f"""<|im_start|>system
你是一位專業的會議秘書。以下是從會議各個時間段抓取的「原始重點列表」,包含重複內容。

任務要求:
1. **去重合併**:將重複的重點整合。
2. **結構化**:使用 Markdown 條列式。
3. **絕對禁止**輸出 `<think>` 標籤。
4. **繁體中文**。

輸出格式範例:
### 1. [分類標題]
- **[關鍵詞]**:[說明]

<|im_end|>
<|im_start|>user
原始資料:
{combined_text[:7000]}

請生成最終重點報告:
<|im_end|>
<|im_start|>assistant
"""
    try:
        out = extractor.model(
            prompt,
            max_tokens=2000,
            temperature=0.2,
            repeat_penalty=1.1,
            stop=["<|im_end|>"],
        )
        return MeetingWorkflow._clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return "[generate_keypoints_summary] 總結生成失敗"


def extract_raw_decisions(extractor, text: str) -> str:
    """提取決策"""
    if len(text) < 50:
        return ""
    prompt = f"""<|im_start|>system
你是一個專業的議事紀錄員。請從會議記錄中提取「明確的決策、承諾、共識或關鍵訴求」。

【嚴格要則】:
1. **只提取實質內容**:如「教育部承諾...」、「工會建議...」、「主席裁示...」。
2. **排除廢話**:不要開場白、不要自我介紹、不要議程說明。
3. **若無決策**:請回答「無」。
4. **繁體中文**。

格式:- [主詞]:[決策/承諾內容]
<|im_end|>
<|im_start|>user
會議片段:
{text[:3500]}

請列出重點:
<|im_end|>
<|im_start|>assistant
"""
    try:
        out = extractor.model(
            prompt,
            max_tokens=500,
            temperature=0.1,
            repeat_penalty=1.1,
            stop=["<|im_end|>"],
        )
        return MeetingWorkflow._clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return ""


def generate_final_decision_report(extractor, raw_list: List[str]) -> str:
    """生成最終決策報告"""
    combined_text = "\n".join(raw_list)
    prompt = f"""<|im_start|>system
你是一位政策分析師。請將以下「原始決策列表」整理成一份精簡的決策報告。
務必**去重合併**,並將同一主題的決策歸類在一起。

【輸出格式】:
### 1. 核心決策與承諾
- [重要性高] ...

### 2. 關鍵訴求與建議
- [重要性中] ...

### 3. 後續行動 (Next Steps)
- [待辦事項] ...

(若某類別無內容可省略)
<|im_end|>
<|im_start|>user
原始資料:
{combined_text}

請生成決策報告:
<|im_end|>
<|im_start|>assistant
"""
    try:
        out = extractor.model(
            prompt,
            max_tokens=1500,
            temperature=0.1,
            stop=["<|im_end|>"],
        )
        return MeetingWorkflow._clean_thought_tags(out["choices"][0]["text"].strip())
    except Exception:
        return "報告生成失敗"


# ==========================================
# 將 extract 函數整合回 step3
# ==========================================
def run_step3_with_extracts(workflow: MeetingWorkflow) -> bool:
    """step3 完整實作版本"""
    workflow._print_banner("步驟 3/6: 生成 People/Keypoints/Decisions 報告")

    srt_files = workflow._list_srt_files()
    if not srt_files:
        print("[run_step3_with_extracts] 找不到任何 SRT(請先完成 ASR)\n")
        return False

    if not os.path.exists(workflow.model_path):
        print(f"[run_step3_with_extracts] 找不到模型: {workflow.model_path}\n")
        return False

    from core1 import LlamaCppQwen3Extractor

    try:
        model_load_start = time.perf_counter()
        print("[run_step3_with_extracts] 正在導入模型...")
        extractor = LlamaCppQwen3Extractor(model_path=workflow.model_path)
        model_load_time = time.perf_counter() - model_load_start
        print(f"[run_step3_with_extracts] 模型導入完成")
        print(f"[run_step3_with_extracts]  模型導入耗時: {model_load_time:.2f} 秒\n")
    except Exception as e:
        print(f"[run_step3_with_extracts] 引擎啟動失敗: {e}\n")
        return False

    people_reports = []
    keypoints_reports = []
    decisions_reports = []

    print(f"[run_step3_with_extracts] 找到 {len(srt_files)} 個字幕檔案,開始產生 P/K/D 報告...\n")

    for idx, srt in enumerate(srt_files, 1):
        srt_path = str(srt)
        stem = srt.stem
        out_p = os.path.join(workflow.output_dir, f"finalp_{stem}.md")
        out_k = os.path.join(workflow.output_dir, f"finalk_{stem}.md")
        out_d = os.path.join(workflow.output_dir, f"finald_{stem}.md")

        print(f"[run_step3_with_extracts] --- ({idx}/{len(srt_files)}) {srt.name} ---")

        subtitles = workflow._parse_srt_brute_force(srt_path)
        if not subtitles:
            print(f"[run_step3_with_extracts] 字幕讀取失敗,略過\n")
            continue

        segments = workflow._split_subtitles_to_segments(subtitles)
        if not segments:
            print(f"[run_step3_with_extracts] 切割後沒有片段,略過\n")
            continue

        # ---- People ----
        raw_people = []
        for seg in segments:
            r = extract_raw_people(extractor, seg)
            if r and len(r) > 3 and "無" not in r and "<think>" not in r:
                raw_people.append(r)
            if hasattr(extractor, "aggressive_memory_cleanup"):
                extractor.aggressive_memory_cleanup()

        if raw_people:
            people_final = generate_final_people_summary(extractor, raw_people)
        else:
            people_final = "## 尚無特定人物\n系統分析本段會議記錄後,未能識別出具體的人員姓名或職稱。"

        with open(out_p, "w", encoding="utf-8") as f:
            f.write("# 會議參與人員名單\n")
            f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(people_final.strip() + "\n")
            f.write("\n\n---\n## 原始提取紀錄 (備份)\n\n")
            f.write("\n\n".join(raw_people))

        # ---- Keypoints ----
        raw_kps = []
        for seg in segments:
            label = seg.split("\n")[0].strip()
            r = extract_raw_keypoints(extractor, seg)
            if r and len(r) > 5 and "無" not in r:
                raw_kps.append(f"{label}\n{r}")
            if hasattr(extractor, "aggressive_memory_cleanup"):
                extractor.aggressive_memory_cleanup()

        if raw_kps:
            k_final = generate_final_keypoints_summary(extractor, raw_kps)
        else:
            k_final = "## 尚無明確重點\n系統分析本段會議記錄後,未發現具體的討論重點或結論。"

        with open(out_k, "w", encoding="utf-8") as f:
            f.write("# 會議核心重點總結\n")
            f.write(f"分析時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(k_final.strip() + "\n")
            f.write("\n\n---\n## 原始提取紀錄\n\n")
            f.write("\n\n".join(raw_kps))

        # ---- Decisions ----
        raw_ds = []
        for seg in segments:
            r = extract_raw_decisions(extractor, seg)
            if r and "無" not in r and len(r) > 5:
                raw_ds.append(r)
            if hasattr(extractor, "aggressive_memory_cleanup"):
                extractor.aggressive_memory_cleanup()

        if raw_ds:
            d_final = generate_final_decision_report(extractor, raw_ds)
        else:
            d_final = "## 尚無明確決策\n系統分析本段會議記錄後,未發現明確的承諾、決議或共識。"

        with open(out_d, "w", encoding="utf-8") as f:
            f.write("# 會議決策重點報告\n")
            f.write(f"時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(d_final.strip() + "\n")
            f.write("\n\n---\n## 原始提取紀錄 (備份)\n\n")
            f.write("\n\n".join(raw_ds))

        print(f" People  輸出: {out_p}")
        print(f" Keypts  輸出: {out_k}")
        print(f" Decisn  輸出: {out_d}\n")

        people_reports.append(people_final.strip())
        keypoints_reports.append(k_final.strip())
        decisions_reports.append(d_final.strip())

    workflow.cache["people"] = "\n\n".join(people_reports).strip() or "(無)"
    workflow.cache["keypoints"] = "\n\n".join(keypoints_reports).strip() or "(無)"
    workflow.cache["decisions"] = "\n\n".join(decisions_reports).strip() or "(無)"

    print("[run_step3_with_extracts] step3 完成:P/K/D 已寫入 cache\n")
    return True


# 覆寫 MeetingWorkflow.step3_run_pkd_reports
#MeetingWorkflow.step3_run_pkd_reports = run_step3_with_extracts


# ==========================================
# 主程式入口
# ==========================================
def main():
    """主程式"""
    workflow = MeetingWorkflow(
        audio_device="hw:2,0",
        output_dir=".",
        output_prefix="output",
        model_path="/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf",
        interval_minutes=5,
        overlap_seconds=60,
        enable_bluetooth=True,           # 啟用藍牙傳送
        enable_proximity_monitor=False,  # 選用:藍牙監控
        enable_recording=True,            # 測試階段先關閉錄音，直接用既有音訊檔
        include_actions_and_summary_files=False,  # False: 不包含 actions/summary，僅傳送最終總報告 TXT
        include_decisions_in_final_txt=False,  # False: 最終總報告不包含 Decisions
    )
    
    success = workflow.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    
    # 設置 D-Bus 主循環
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    main()