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
import datetime
import threading
from pathlib import Path
from typing import List, Dict, Optional
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# --------------------------------------------------
# 將專案根目錄加入 Python 路徑
# --------------------------------------------------
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


# ==========================================
# 藍牙 OBEX 檔案傳送模組
# ==========================================
class ObexPushError(Exception):
    """OBEX 傳送錯誤"""
    pass


class BluetoothFileSender:
    """藍牙檔案傳送器 (OBEX Push)"""
    
    def __init__(self):
        self.bus = dbus.SystemBus()
        
    def get_paired_devices(self):
        """取得已配對的藍牙裝置"""
        try:
            manager = dbus.Interface(
                self.bus.get_object("org.bluez", "/"),
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
            raise ObexPushError(f"無法取得配對裝置: {e}")
    
    def send_file(self, file_path: str, device_mac: str) -> bool:
        try:
            bus = _get_obex_bus()

            # OBEX client
            client = dbus.Interface(
                bus.get_object("org.bluez.obex", "/org/bluez/obex"),
                "org.bluez.obex.Client1"
            )

            session_path = client.CreateSession(
                device_mac,
                {"Target": "OPP"}
            )

            obj_push = dbus.Interface(
                bus.get_object("org.bluez.obex", session_path),
                "org.bluez.obex.ObjectPush1"
            )

            transfer_path, _ = obj_push.SendFile(file_path)

            # 等待完成
            props = dbus.Interface(
                bus.get_object("org.bluez.obex", transfer_path),
                "org.freedesktop.DBus.Properties"
            )

            timeout = 30
            while timeout > 0:
                status = str(props.Get("org.bluez.obex.Transfer1", "Status"))
                if status == "complete":
                    return True
                if status == "error":
                    raise ObexPushError("傳送失敗")
                time.sleep(0.5)
                timeout -= 0.5

            raise ObexPushError("傳送逾時")

        except dbus.exceptions.DBusException as e:
            raise ObexPushError(f"D-Bus 錯誤: {e}")

    
    def auto_send_to_first_paired(self, files: List[str]) -> tuple:
        """
        自動傳送檔案到第一個配對的裝置
        
        Args:
            files: 要傳送的檔案列表
            
        Returns:
            (mac, name) 成功傳送的裝置資訊
        """
        devices = self.get_paired_devices()
        
        if not devices:
            raise ObexPushError("沒有已配對的裝置")
        
        # 優先選擇已連線的裝置
        target = None
        for dev in devices:
            if dev["connected"]:
                target = dev
                break
        
        if not target:
            target = devices[0]
        
        print(f"📱 目標裝置: {target['name']} ({target['mac']})")
        
        for file_path in files:
            if not os.path.exists(file_path):
                print(f"⚠️  檔案不存在: {file_path}")
                continue
                
            print(f"📤 傳送: {os.path.basename(file_path)}...")
            self.send_file(file_path, target['mac'])
            print(f"✅ 完成")
            time.sleep(0.5)
        
        return target['mac'], target['name']
    


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
        enable_bluetooth=True,
        enable_proximity_monitor=False,
    ):
        self.audio_device = audio_device
        self.output_dir = output_dir
        self.output_prefix = output_prefix
        self.model_path = model_path
        self.interval_minutes = interval_minutes
        self.overlap_seconds = overlap_seconds

        self.audio_file = os.path.join(output_dir, f"{output_prefix}_audio.mkv")
        self.actions_file = os.path.join(output_dir, f"{output_prefix}_actions.txt")
        self.summary_file = os.path.join(output_dir, f"{output_prefix}_summary.txt")
        self.txt_file = os.path.join(output_dir, f"{output_prefix}_meeting_summary.txt")
        
        self.dump_cache_in_txt = False
        self.enable_bluetooth = enable_bluetooth
        self.enable_proximity_monitor = enable_proximity_monitor

        os.makedirs(output_dir, exist_ok=True)
        self.is_recording = False
        self.cache: Dict[str, object] = {}
        
        # 藍牙模組
        if self.enable_bluetooth:
            try:
                self.bt_sender = BluetoothFileSender()
                print("✅ 藍牙傳送模組已啟用")
            except Exception as e:
                print(f"⚠️  藍牙傳送模組啟動失敗: {e}")
                self.enable_bluetooth = False
        
        if self.enable_proximity_monitor:
            try:
                self.bt_monitor = BluetoothProximityMonitor()
                print("✅ 藍牙監控模組已啟用")
            except Exception as e:
                print(f"⚠️  藍牙監控模組啟動失敗: {e}")
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
                print(f"📖 使用編碼 {enc} 讀取成功,共 {len(lines)} 行")
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

        print(f"⏱️ 偵測 SRT 時間範圍: {int(min_time)}秒 ~ {int(max_time)}秒")
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
                segments.append(f"【時間段 {label}】\n" + "\n".join(current_text_list))

        return segments

    # ------------------------
    # step1: 錄音
    # ------------------------
    def step1_record(self) -> bool:
        self._print_banner("步驟 1/6: 開始錄音")
        print(f"🎤 音訊設備: {self.audio_device}")
        print(f"📁 輸出檔案: {self.audio_file}")
        print("⌨️  按 Ctrl+C 結束錄音\n")

        arecord_cmd = [
            "arecord",
            "-D", self.audio_device,
            "-f", "S16_LE",
            "-c", "1",
            "-r", "16000",
        ]

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f", "s16le",
            "-ar", "16000",
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
                print("\n\n🛑 正在停止錄音...")
                self.is_recording = False

        try:
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

            print("✅ 錄音進行中...\n")
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

        if os.path.exists(self.audio_file):
            print("✅ 錄音已停止")
            print(f"💾 音訊檔案已儲存: {self.audio_file}\n")
            return True

        print("❌ 找不到錄音輸出檔\n")
        return False

    # ------------------------
    # step2: ASR
    # ------------------------
    def step2_transcribe(self) -> bool:
        self._print_banner("步驟 2/6: 語音轉文字 (ASR)")
        print(f"📂 讀取音訊: {self.audio_file}")
        print("⌨️  按 Ctrl+C 可提前結束轉錄\n")

        if not os.path.exists(self.audio_file):
            print("❌ 音訊檔不存在\n")
            return False

        conda_python = "/home/cgu-csie/miniconda3/bin/python3"
        asr_script = os.path.join(project_root, "speech", "run_asr_conda.py")

        cmd = [
            "sudo", "-u", "cgu-csie",         # ✅ 重要：用你的帳號跑 conda，不要用 root
            conda_python,
            asr_script,
            "--audio", self.audio_file,
            "--outdir", self.output_dir,
            "--prefix", self.output_prefix,
            "--alpha", "0.0",
            "--overlap", "5.0",
            "--verbose",
        ]

        print("🚀 使用 conda Python 執行 ASR：")
        print("   " + " ".join(cmd) + "\n")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

        try:
            subprocess.run(cmd, check=True, cwd=str(project_root), env=env)
        except subprocess.CalledProcessError as e:
            print(f"❌ ASR 失敗: {e}\n")
            return False
        print("✅ ASR 轉錄完成\n")
        return True


    # ------------------------
    # step3: People/Keypoints/Decisions
    # ------------------------
    def step3_run_pkd_reports(self) -> bool:
        self._print_banner("步驟 3/6: 生成 People/Keypoints/Decisions 報告 (conda worker)")

        if not os.path.exists(self.model_path):
            print(f"❌ 找不到模型: {self.model_path}\n")
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

        print("🚀 使用 conda Python 執行 PKD：")
        print("   " + " ".join(cmd) + "\n")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

        try:
            subprocess.run(cmd, check=True, cwd=str(project_root), env=env)
        except subprocess.CalledProcessError as e:
            print(f"❌ PKD 失敗: {e}\n")
            return False
    # 讀回結果
        try:
            import json
            if not os.path.exists(out_json):
                print(f"❌ 找不到 PKD 輸出: {out_json}\n")
                return False
            with open(out_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cache["people"] = data.get("people", "").strip() or "(無)"
            self.cache["keypoints"] = data.get("keypoints", "").strip() or "(無)"
            self.cache["decisions"] = data.get("decisions", "").strip() or "(無)"
        except Exception as e:
            print(f"❌ 讀取 PKD 結果失敗: {e}\n")
            return False

        print("✅ step3 完成：P/K/D 已寫入 cache\n")
        
        return True


    # ------------------------
    # step4: Actions
    # ------------------------
    def step4_extract_actions(self) -> bool:
        self._print_banner("步驟 4/6: 提取行動項目 (conda worker)")

        conda_python = "/home/cgu-csie/miniconda3/bin/python3"
        worker = os.path.join(project_root, "run_actions_conda.py")
        out_json = os.path.join(self.output_dir, f"{self.output_prefix}_actions_cache.json")
        cmd = [
            "sudo", "-u", "cgu-csie",
            conda_python, worker,
            "--output-dir", self.output_dir,
            "--output-prefix", self.output_prefix,
        ]

        print("🚀 使用 conda Python 執行 Actions：")
        print("   " + " ".join(cmd) + "\n")

        try:
            subprocess.run(cmd, check=True, cwd=str(project_root))
        except subprocess.CalledProcessError as e:
            print(f"❌ Actions 失敗: {e}\n")
            return False

        # 讀回結果
        try:
            import json
            if not os.path.exists(out_json):
                print(f"❌ 找不到 Actions 輸出: {out_json}\n")
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
        except Exception as e:
            print(f"❌ 讀取 Actions 結果失敗: {e}\n")
            return False

        print(f"💾 行動項目已輸出: {self.actions_file}\n")
        return True


    # ------------------------
    # step5: Summary
    # ------------------------
    def step5_generate_summary(self) -> bool:
        self._print_banner("步驟 5/6: 生成會議摘要 (conda worker)")

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
        print("🚀 使用 conda Python 執行 Summary：")
        print("   " + " ".join(cmd) + "\n")

        try:
            subprocess.run(cmd, check=True, cwd=str(project_root))
        except subprocess.CalledProcessError as e:
            print(f"❌ Summary 失敗: {e}\n")
            return False
        try:
            import json
            if not os.path.exists(out_json):
                print(f"❌ 找不到 Summary 輸出: {out_json}\n")
                return False

            with open(out_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.cache["summary"] = data.get("summary", "").strip() or "(無摘要)"

            # 同步輸出 TXT（系統端 I/O）
            summary_txt = os.path.join(
                self.output_dir, f"{self.output_prefix}_summary.txt"
            )
            with open(summary_txt, "w", encoding="utf-8") as f:
                f.write("會議摘要\n" + "=" * 60 + "\n\n")
                f.write(self.cache["summary"] + "\n")

            print(f"💾 摘要已輸出: {summary_txt}\n")

        except Exception as e:
            print(f"❌ 讀取 Summary 結果失敗: {e}\n")
            return False

        return True
    # ------------------------
    # step6: Export TXT + Bluetooth
    # ------------------------
    def step6_export_txt(self) -> bool:
        self._print_banner("步驟 6/6: 匯出 TXT + 藍牙傳送")

        def _write_section(f, title: str, content: str):
            f.write(f"\n{title}\n" + "="*60 + "\n")
            content = (content or "").strip()
            f.write(content if content else "(無)")
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

                _write_section(f, "整體摘要(Summary)", self.cache.get("summary", ""))
                _write_section(f, "與會人員(People)", self.cache.get("people", ""))
                _write_section(f, "會議重點(Keypoints)", self.cache.get("keypoints", ""))
                _write_section(f, "決策事項(Decisions)", self.cache.get("decisions", ""))
                _write_list(f, "行動項目(Actions)", self.cache.get("actions_lines", []))

        except Exception as e:
            print(f"❌ TXT 產生失敗: {e}")
            return False

        print(f"📄 TXT 已輸出: {self.txt_file}\n")

        # =========================
        # ★ 藍牙傳送結果檔案
        # =========================
        if self.enable_bluetooth:
            print("🔵 準備透過藍牙傳送檔案...")
            try:
                files_to_send = [
                    self.txt_file,
                    self.actions_file,
                    self.summary_file,
                ]

                mac, name = self.bt_sender.auto_send_to_first_paired(files_to_send)
                print(f"✅ 藍牙傳送成功: {name} ({mac})\n")

            except ObexPushError as e:
                print(f"⚠️  藍牙傳送失敗: {e}\n")
            except Exception as e:
                print(f"❌ 藍牙未預期錯誤: {e}\n")

        return True

    # ------------------------
    # 主流程
    # ------------------------
    def run(self) -> bool:
        self._print_banner("🎯 會議工作流程控制器 (整合藍牙版)")

        # 啟動藍牙監控 (選用)
        if self.enable_proximity_monitor:
            try:
                devices = self.bt_sender.get_paired_devices()
                if devices:
                    def on_device_change(mac, name, is_nearby):
                        status = "🟢 進入範圍" if is_nearby else "🔴 離開範圍"
                        print(f"\n[藍牙監控] {name}: {status}")
                    
                    monitor_devices = [{"mac": d["mac"], "name": d["name"]} for d in devices[:3]]
                    self.bt_monitor.start_monitoring(monitor_devices, callback=on_device_change)
                    print(f"📡 已啟動藍牙監控: {len(monitor_devices)} 個裝置\n")
            except Exception as e:
                print(f"⚠️  藍牙監控啟動失敗: {e}\n")

        # 執行主要流程
        if not self.step1_record():
            return False
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
                print("📡 藍牙監控已停止\n")
            except Exception as e:
                print(f"⚠️  停止監控失敗: {e}\n")

        self._print_banner("✅ 工作流程完成")
        print("🎉 全流程結束\n")
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
        return "總結生成失敗"


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
        return "總結生成失敗"


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
        print("❌ 找不到任何 SRT(請先完成 ASR)\n")
        return False

    if not os.path.exists(workflow.model_path):
        print(f"❌ 找不到模型: {workflow.model_path}\n")
        return False

    from core1 import LlamaCppQwen3Extractor

    try:
        extractor = LlamaCppQwen3Extractor(model_path=workflow.model_path)
    except Exception as e:
        print(f"❌ 引擎啟動失敗: {e}\n")
        return False

    people_reports = []
    keypoints_reports = []
    decisions_reports = []

    print(f"📄 找到 {len(srt_files)} 個字幕檔案,開始產生 P/K/D 報告...\n")

    for idx, srt in enumerate(srt_files, 1):
        srt_path = str(srt)
        stem = srt.stem
        out_p = os.path.join(workflow.output_dir, f"finalp_{stem}.md")
        out_k = os.path.join(workflow.output_dir, f"finalk_{stem}.md")
        out_d = os.path.join(workflow.output_dir, f"finald_{stem}.md")

        print(f"--- ({idx}/{len(srt_files)}) {srt.name} ---")

        subtitles = workflow._parse_srt_brute_force(srt_path)
        if not subtitles:
            print("⚠️  字幕讀取失敗,略過\n")
            continue

        segments = workflow._split_subtitles_to_segments(subtitles)
        if not segments:
            print("⚠️  切割後沒有片段,略過\n")
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

        print(f"✅ People  輸出: {out_p}")
        print(f"✅ Keypts  輸出: {out_k}")
        print(f"✅ Decisn  輸出: {out_d}\n")

        people_reports.append(people_final.strip())
        keypoints_reports.append(k_final.strip())
        decisions_reports.append(d_final.strip())

    workflow.cache["people"] = "\n\n".join(people_reports).strip() or "(無)"
    workflow.cache["keypoints"] = "\n\n".join(keypoints_reports).strip() or "(無)"
    workflow.cache["decisions"] = "\n\n".join(decisions_reports).strip() or "(無)"

    print("✅ step3 完成:P/K/D 已寫入 cache\n")
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
    )
    
    success = workflow.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # 檢查 root 權限 (藍牙需要)
    if os.geteuid() != 0:
        print("⚠️  此腳本需要 root 權限以使用藍牙功能")
        print("   請使用: sudo python3 meeting_v1_integrated.py")
        sys.exit(1)
    
    # 設置 D-Bus 主循環
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    main()