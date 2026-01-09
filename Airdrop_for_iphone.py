#!/usr/bin/env python3
"""
AirDrop Receiver Manager for Raspberry Pi
自動化管理 OpenDrop，接收 iPhone 的 AirDrop 檔案到指定目錄
"""

import os
import sys
import subprocess
import time
import logging
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable
import signal
import threading

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/airdrop_receiver.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AirDropConfig:
    """OpenDrop 與 OWL 設定"""
    def __init__(self, 
                 receive_dir: str = os.path.expanduser('~/airdrop_inbox'),
                 wlan_iface: str = 'wlan0',
                 owl_channel: int = 6,
                 owl_daemonize: bool = True):
        self.receive_dir = Path(receive_dir).expanduser().absolute()
        self.wlan_iface = wlan_iface
        self.owl_channel = owl_channel
        self.owl_daemonize = owl_daemonize
        self.owl_pid_file = Path(f'/tmp/owl_{wlan_iface}.pid')
        self.opendrop_pid_file = Path('/tmp/opendrop.pid')
        
    def ensure_receive_dir(self):
        """確保接收目錄存在"""
        self.receive_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"接收目錄已準備: {self.receive_dir}")


class OWLManager:
    """管理 OWL daemon (AWDL 實作)"""
    def __init__(self, config: AirDropConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        
    def is_running(self) -> bool:
        """檢查 OWL 是否執行中"""
        try:
            result = subprocess.run(
                ['pgrep', '-f', f'owl.*-i {self.config.wlan_iface}'],
                capture_output=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"檢查 OWL 狀態失敗: {e}")
            return False
    
    def setup_monitor_mode(self) -> bool:
        """將 Wi‑Fi 卡設為 monitor mode"""
        try:
            logger.info(f"設定 {self.config.wlan_iface} 進入 monitor mode...")
            
            # 關閉介面
            subprocess.run(['sudo', 'ifconfig', self.config.wlan_iface, 'down'],
                         check=True, capture_output=True)
            time.sleep(0.5)
            
            # 設為 monitor mode
            subprocess.run(['sudo', 'iw', 'dev', self.config.wlan_iface, 'set', 'type', 'monitor'],
                         check=True, capture_output=True)
            time.sleep(0.5)
            
            # 啟動介面
            subprocess.run(['sudo', 'ifconfig', self.config.wlan_iface, 'up'],
                         check=True, capture_output=True)
            time.sleep(1)
            
            # 驗證
            result = subprocess.run(['iw', 'dev', self.config.wlan_iface, 'info'],
                                  capture_output=True, text=True)
            if 'type: monitor' in result.stdout:
                logger.info(f"{self.config.wlan_iface} 已設為 monitor mode")
                return True
            else:
                logger.error(f"設定 monitor mode 失敗: {result.stdout}")
                return False
                
        except subprocess.CalledProcessError as e:
            logger.error(f"設定 monitor mode 異常: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"設定 monitor mode 異常: {e}")
            return False
    
    def start(self) -> bool:
        """啟動 OWL"""
        if self.is_running():
            logger.warning("OWL 已在執行中")
            return True
        
        try:
            if not self.setup_monitor_mode():
                return False
            
            logger.info(f"啟動 OWL（頻道: {self.config.owl_channel})...")
            
            cmd = ['sudo', 'owl', '-i', self.config.wlan_iface, 
                   '-c', str(self.config.owl_channel), '-v']
            
            if self.config.owl_daemonize:
                cmd.append('-D')
            
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE)
            time.sleep(2)
            
            if self.is_running():
                logger.info("OWL 已啟動成功")
                return True
            else:
                logger.error("OWL 啟動失敗")
                return False
                
        except Exception as e:
            logger.error(f"啟動 OWL 異常: {e}")
            return False
    
    def stop(self):
        """停止 OWL"""
        try:
            subprocess.run(['sudo', 'pkill', '-f', f'owl.*-i {self.config.wlan_iface}'],
                         check=False)
            logger.info("OWL 已停止")
        except Exception as e:
            logger.error(f"停止 OWL 異常: {e}")
    
    def verify_awdl_interface(self) -> bool:
        """驗證 awdl0 虛擬介面是否存在"""
        try:
            result = subprocess.run(['ip', 'addr', 'show', 'awdl0'],
                                  capture_output=True)
            return result.returncode == 0
        except:
            return False


class OpenDropReceiver:
    """管理 OpenDrop 接收"""
    def __init__(self, config: AirDropConfig, on_file_received: Optional[Callable] = None):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.on_file_received = on_file_received or self._default_handler
        self.stop_event = threading.Event()
        
    def _default_handler(self, filepath: Path):
        """預設的檔案接收處理器"""
        logger.info(f"✓ 檔案已接收: {filepath}")
        logger.info(f"  大小: {filepath.stat().st_size} bytes")
        logger.info(f"  時間: {datetime.fromtimestamp(filepath.stat().st_mtime)}")
    
    def start(self) -> bool:
        """啟動 OpenDrop receive"""
        try:
            self.config.ensure_receive_dir()
            
            logger.info(f"啟動 OpenDrop receive（接收目錄: {self.config.receive_dir})...")
            
            cmd = ['opendrop', 'receive']
            
            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.config.receive_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            time.sleep(1)
            
            if self.process.poll() is None:  # 仍在執行
                logger.info("OpenDrop receive 已啟動")
                # 啟動檔案監視執行緒
                self._start_file_monitor()
                return True
            else:
                stdout, stderr = self.process.communicate()
                logger.error(f"OpenDrop 啟動失敗: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"啟動 OpenDrop 異常: {e}")
            return False
    
    def _start_file_monitor(self):
        """啟動檔案監視執行緒"""
        def monitor():
            known_files = set(self.config.receive_dir.glob('*'))
            
            while not self.stop_event.is_set():
                try:
                    current_files = set(self.config.receive_dir.glob('*'))
                    new_files = current_files - known_files
                    
                    for file in new_files:
                        if file.is_file():
                            logger.info(f"偵測到新檔案: {file.name}")
                            self.on_file_received(file)
                    
                    known_files = current_files
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"檔案監視異常: {e}")
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def stop(self):
        """停止 OpenDrop receive"""
        self.stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            logger.info("OpenDrop receive 已停止")


class AirDropReceiverManager:
    """整合式 AirDrop 接收管理器"""
    def __init__(self, config: AirDropConfig, 
                 on_file_received: Optional[Callable] = None):
        self.config = config
        self.owl = OWLManager(config)
        self.opendrop = OpenDropReceiver(config, on_file_received)
        self.running = False
    
    def setup(self) -> bool:
        """完整設定（OWL + OpenDrop）"""
        logger.info("=" * 50)
        logger.info("AirDrop 接收管理器 - 初始化")
        logger.info("=" * 50)
        
        # 1. 啟動 OWL
        if not self.owl.start():
            logger.error("OWL 啟動失敗，放棄繼續")
            return False
        
        time.sleep(2)
        
        # 2. 驗證 awdl0
        if not self.owl.verify_awdl_interface():
            logger.error("AWDL 虛擬介面不存在，放棄繼續")
            return False
        
        logger.info("✓ AWDL 虛擬介面已建立")
        
        # 3. 啟動 OpenDrop
        if not self.opendrop.start():
            logger.error("OpenDrop 啟動失敗")
            self.owl.stop()
            return False
        
        self.running = True
        logger.info("=" * 50)
        logger.info("✓ AirDrop 接收管理器已就緒")
        logger.info(f"  iPhone 現在可以透過 AirDrop 傳送檔案到此裝置")
        logger.info(f"  接收目錄: {self.config.receive_dir}")
        logger.info("=" * 50)
        
        return True
    
    def run(self):
        """執行接收迴圈"""
        if not self.setup():
            sys.exit(1)
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n使用者中斷")
            self.shutdown()
    
    def shutdown(self):
        """優雅關閉"""
        logger.info("關閉 AirDrop 接收管理器...")
        self.running = False
        self.opendrop.stop()
        self.owl.stop()
        logger.info("已關閉")


# 示範：自訂檔案接收處理器
def custom_file_handler(filepath: Path):
    """
    接收檔案後的自訂處理邏輯
    例如：複製、轉檔、病毒掃描、記錄到數據庫等
    """
    logger.info(f"[自訂處理] 處理檔案: {filepath.name}")
    
    # 示例 1：按檔案類型分類
    if filepath.suffix.lower() in ['.jpg', '.jpeg', '.png', '.heic']:
        media_dir = filepath.parent / 'images'
        media_dir.mkdir(exist_ok=True)
        dest = media_dir / filepath.name
        shutil.move(str(filepath), str(dest))
        logger.info(f"  → 已移到: {dest}")
    
    elif filepath.suffix.lower() in ['.mp4', '.mov', '.m4v']:
        media_dir = filepath.parent / 'videos'
        media_dir.mkdir(exist_ok=True)
        dest = media_dir / filepath.name
        shutil.move(str(filepath), str(dest))
        logger.info(f"  → 已移到: {dest}")
    
    # 示例 2：記錄檔案元數據到 JSON
    metadata = {
        'filename': filepath.name,
        'size_bytes': filepath.stat().st_size,
        'received_at': datetime.fromtimestamp(
            filepath.stat().st_mtime
        ).isoformat(),
        'suffix': filepath.suffix
    }
    
    log_file = filepath.parent / 'airdrop_log.json'
    records = []
    if log_file.exists():
        with open(log_file, 'r') as f:
            records = json.load(f)
    
    records.append(metadata)
    with open(log_file, 'w') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    
    logger.info(f"  → 已記錄到日誌")


if __name__ == '__main__':
    # 設定（可根據需要調整）
    config = AirDropConfig(
        receive_dir='~/airdrop_inbox',
        wlan_iface='wlan0',
        owl_channel=6,
        owl_daemonize=True
    )
    
    # 建立管理器（使用自訂處理器或預設）
    manager = AirDropReceiverManager(
        config,
        on_file_received=custom_file_handler
    )
    
    # 執行
    manager.run()
