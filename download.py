import csv
import encodings.idna  # avoid encoding error in distributable
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
import traceback
import queue

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QProgressBar, QPushButton, 
                            QTextEdit, QFileDialog, QSpinBox, QGroupBox, 
                            QFormLayout, QStyleFactory, QMessageBox, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject, QThreadPool, QRunnable
from PyQt5.QtGui import QFont, QFontDatabase, QPainter, QColor, QLinearGradient, QBrush, QPen

# Default values
DEFAULT_THREAD_COUNT = 5  # Reduced for stability
# Adjust max filename length based on platform
if platform.system() == "Windows":
    DEFAULT_MAX_FILENAME_LENGTH = 255  # Windows NTFS/FAT32 limit
elif platform.system() == "Darwin":  # macOS
    DEFAULT_MAX_FILENAME_LENGTH = 255  # macOS HFS+/APFS limit
else:  # Linux and others
    DEFAULT_MAX_FILENAME_LENGTH = 143  # Conservative for all Linux filesystems (ecryptfs limit)

# Platform-specific default output directory
if platform.system() == "Windows":
    DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "BBCSounds")
elif platform.system() == "Darwin":  # macOS
    DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Music", "BBCSounds")
else:  # Linux and others
    DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "BBCSounds")

DEFAULT_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30  # seconds

# Aero Glass styling constants
AERO_BLUE = "#2a8dd4"
AERO_LIGHT_BLUE = "#bce4fa"
AERO_GLASS_START = "rgba(220, 240, 255, 150)"
AERO_GLASS_END = "rgba(200, 230, 255, 100)"
AERO_BUTTON_GRADIENT_START = "#f8f8f8"
AERO_BUTTON_GRADIENT_END = "#e1e1e1" 
AERO_BUTTON_HOVER_START = "#ebf4fd"
AERO_BUTTON_HOVER_END = "#d8eef9"
AERO_BUTTON_PRESSED_START = "#cbe8fb"
AERO_BUTTON_PRESSED_END = "#a5d8f8"
AERO_BUTTON_BORDER = "#8bade6"
AERO_BUTTON_BORDER_HOVER = "#5ea6e1"

# Platform-specific settings
SYSTEM = platform.system()
IS_WINDOWS = SYSTEM == "Windows"
IS_LINUX = SYSTEM == "Linux"
IS_MAC = SYSTEM == "Darwin"

# Font selection based on platform
def get_platform_font():
    if IS_WINDOWS:
        return "Segoe UI"
    elif IS_LINUX:
        return "Ubuntu, DejaVu Sans, Sans-Serif"
    elif IS_MAC:
        return "SF Pro Display, Helvetica Neue, Helvetica"
    else:
        return "Sans-Serif"

AERO_FONT = get_platform_font()


class AeroFrame(QFrame):
    """Custom QFrame with Aero Glass-like appearance"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aeroFrame")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            #aeroFrame {
                background-color: rgba(255, 255, 255, 180);
                border: 1px solid rgba(150, 180, 220, 150);
                border-radius: 6px;
            }
        """)


class AeroGroupBox(QGroupBox):
    """Custom QGroupBox with Aero Glass-like appearance"""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setObjectName("aeroGroupBox")
        
        # Apply custom style
        self.setStyleSheet(f"""
            QGroupBox#aeroGroupBox {{
                background-color: rgba(255, 255, 255, 150);
                border: 1px solid rgba(150, 180, 220, 150);
                border-radius: 6px;
                margin-top: 22px;
                font-family: '{AERO_FONT}';
                font-size: 10pt;
                font-weight: bold;
                color: rgba(0, 60, 120, 255);
            }}
            QGroupBox#aeroGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px 0 5px;
            }}
        """)


# Signals need to be defined on a QObject
class DownloadSignals(QObject):
    """Signals for the download worker"""
    progress = pyqtSignal(str, str, int)   # filepath_str, status_text, percent
    finished = pyqtSignal(bool, str, str)  # success, filepath_str, error_msg


class DownloadWorker(QRunnable):
    """Worker for downloading files using QRunnable for thread pooling"""
    
    def __init__(self, url, filepath, fallback_urls=None, timeout=DEFAULT_TIMEOUT, retry_count=DEFAULT_RETRY_COUNT):
        super().__init__()
        
        # Set low priority
        self.setAutoDelete(True)  # Let the thread pool manage deletion
        
        self.url = url
        self.filepath = filepath
        self.fallback_urls = fallback_urls or []
        self.timeout = timeout
        self.retry_count = retry_count
        
        # Flag to check if task was requested to stop
        self.is_cancelled = False
        
        # Create signals object
        self.signals = DownloadSignals()
    
    def run(self):
        """Main task execution method"""
        filepath_str = str(self.filepath)
        try:
            self.signals.progress.emit(filepath_str, f"Starting download: {self.filepath.name}", 0)
            
            # Check if cancelled
            if self.is_cancelled:
                self.signals.progress.emit(filepath_str, f"Download cancelled: {self.filepath.name}", 0)
                return
            
            # Try the primary URL first
            if self._try_download(self.url, self.retry_count):
                return
                
            # Check if cancelled
            if self.is_cancelled:
                self.signals.progress.emit(filepath_str, f"Download cancelled: {self.filepath.name}", 0)
                return
                
            # If primary URL fails, try fallbacks
            if self.fallback_urls:
                self.signals.progress.emit(
                    filepath_str, f"Primary URL failed, trying alternatives for: {self.filepath.name}", 0
                )
                
                for fallback_url in self.fallback_urls:
                    # Check if cancelled
                    if self.is_cancelled:
                        self.signals.progress.emit(filepath_str, f"Download cancelled: {self.filepath.name}", 0)
                        return
                        
                    if self._try_download(fallback_url, 1):  # Only try once for each fallback
                        return
                        
            # If we get here, all URLs failed
            if not self.is_cancelled:
                self.signals.progress.emit(filepath_str, f"All URLs failed for: {self.filepath.name}", 0)
                self.signals.finished.emit(False, filepath_str, "All download URLs failed")
        except Exception as e:
            # Handle any uncaught exceptions to prevent crashes
            if not self.is_cancelled:
                self.signals.progress.emit(filepath_str, f"Error in download thread: {self.filepath.name}", 0)
                self.signals.finished.emit(False, filepath_str, f"Thread error: {str(e)}")
    
    def _try_download(self, url, max_attempts):
        """Try to download from a specific URL with multiple attempts"""
        filepath_str = str(self.filepath)
        for attempt in range(1, max_attempts + 1):
            # Check if cancelled
            if self.is_cancelled:
                return False
                
            try:
                # Create all parent directories first
                try:
                    self.filepath.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Set appropriate permissions on Linux
                    if IS_LINUX:
                        try:
                            # Make sure parent directory is writable, readable and executable
                            parent_dir = self.filepath.parent
                            os.chmod(parent_dir, 0o755)  # rwxr-xr-x
                        except Exception as e:
                            # Log but continue - this is not fatal
                            print(f"Warning: Failed to set directory permissions: {e}")
                except Exception as e:
                    self.signals.progress.emit(filepath_str, f"Error creating directories: {str(e)}", 0)
                    raise e
                
                # Add custom headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 Python BBC Sound Effects Downloader',
                    'Referer': 'https://sound-effects.bbcrewind.co.uk/'
                }
                request = urllib.request.Request(url, headers=headers)
                
                # Setup progress reporter
                def report_progress(block_num, block_size, total_size):
                    # Check if cancelled during download
                    if self.is_cancelled:
                        raise Exception("Download cancelled by user")
                        
                    if total_size > 0:
                        percent = min(int(block_num * block_size * 100 / total_size), 100)
                        self.signals.progress.emit(
                            filepath_str, 
                            f"Downloading from {url.split('/')[2]}: {self.filepath.name}", 
                            percent
                        )
                
                # Create a temporary file with a platform-appropriate path
                temp_fd, temp_path = tempfile.mkstemp(prefix='bbc_download_')
                os.close(temp_fd)  # Close the file descriptor
                
                try:
                    # Check if cancelled
                    if self.is_cancelled:
                        return False
                        
                    # Download with progress reporting
                    urllib.request.urlretrieve(url, temp_path, reporthook=report_progress)
                    
                    # Check if cancelled after download
                    if self.is_cancelled:
                        if os.path.exists(temp_path):
                            try:
                                os.remove(temp_path)
                            except:
                                pass
                        return False
                    
                    # Verify the download
                    if os.path.getsize(temp_path) == 0:
                        raise Exception("Downloaded file is empty")
                    
                    # Ensure destination directory exists again (could have been deleted)
                    self.filepath.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Move to final location
                    shutil.move(temp_path, self.filepath)
                    
                    # Set appropriate file permissions on Linux/Mac
                    if not IS_WINDOWS:
                        try:
                            os.chmod(self.filepath, 0o644)  # rw-r--r--
                        except Exception as e:
                            # Log but continue - this is not fatal
                            print(f"Warning: Failed to set file permissions: {e}")
                            
                    # Only emit signals if not cancelled
                    if not self.is_cancelled:
                        self.signals.progress.emit(filepath_str, f"Completed: {self.filepath.name}", 100)
                        self.signals.finished.emit(True, filepath_str, "")
                    return True  # Download successful
                    
                except Exception as e:
                    # Clean up temp file if it exists
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except:
                            pass
                    # If cancellation caused the exception, return quietly
                    if self.is_cancelled:
                        return False
                    raise e
                
            except Exception as e:
                error_msg = str(e)
                
                # If cancelled, return quietly
                if self.is_cancelled:
                    return False
                    
                if attempt < max_attempts:
                    self.signals.progress.emit(
                        filepath_str, 
                        f"Retry {attempt}/{max_attempts} from {url.split('/')[2]}: {self.filepath.name}", 
                        0
                    )
                    
                    # Sleep for backoff, but check cancellation periodically
                    backoff_time = 2 ** attempt
                    start_time = time.time()
                    while time.time() - start_time < backoff_time:
                        if self.is_cancelled:
                            return False
                        time.sleep(0.1)  # Sleep in small increments to check cancellation
                else:
                    self.signals.progress.emit(
                        filepath_str, 
                        f"Failed from {url.split('/')[2]}: {self.filepath.name}",
                        0
                    )
        
        return False  # All attempts failed


class BBCSoundDownloaderGUI(QMainWindow):
    """Main application window"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BBC Sound Effects Downloader - Thread Pool Edition")
        self.setMinimumSize(800, 600)
        
        # State variables
        self.samples = []
        self.total_count = 0
        self.finished_count = 0
        self.failed_count = 0
        self.active_downloads = {}
        self.output_dir = Path(DEFAULT_OUTPUT_DIR)
        self.csv_file_path = None
        
        # Set up thread pool
        self.thread_pool = QThreadPool.globalInstance()
        
        # Flag to track if we're shutting down to prevent race conditions
        self.is_shutting_down = False
        
        # Ensure output directory exists on startup
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            if IS_LINUX:
                os.chmod(self.output_dir, 0o755)  # rwxr-xr-x
        except Exception as e:
            print(f"Warning: Failed to create output directory: {e}")
        
        # Setup UI
        self.init_ui()
        self.apply_aero_style()
        
        # Setup timer for UI updates to reduce overhead
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.process_download_queue)
        self.update_timer.start(100)  # Update every 100ms
        
        # Queue for handling completed downloads
        self.download_results_queue = queue.Queue()
    
    def init_ui(self):
        # Main widget and layout
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet("""
            #centralWidget {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                               stop:0 #f0f6ff, stop:1 #e0ecfa);
            }
        """)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # Header with Aero Glass banner
        header_frame = AeroFrame()
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(15, 15, 15, 15)
        
        # Title and subtitle
        title_label = QLabel("BBC Sound Effects Downloader")
        title_label.setStyleSheet(
            f"font-family: '{AERO_FONT}'; font-size: 20pt; font-weight: bold; "
            f"color: {AERO_BLUE}; background: transparent;"
        )
        subtitle_label = QLabel("Thread Pool Edition")
        subtitle_label.setStyleSheet(
            f"font-family: '{AERO_FONT}'; font-size: 11pt; "
            f"color: #444444; background: transparent;"
        )
        
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        main_layout.addWidget(header_frame)
        
        # File selection panel
        file_group = AeroGroupBox("Data Source")
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(15, 25, 15, 15)
        
        # CSV file selection
        csv_layout = QHBoxLayout()
        csv_label = QLabel("CSV File:")
        csv_label.setStyleSheet(f"font-family: '{AERO_FONT}'; font-size: 10pt;")
        
        self.csv_edit = QTextEdit()
        self.csv_edit.setFixedHeight(28)
        self.csv_edit.setReadOnly(True)
        self.csv_edit.setPlaceholderText("Select BBC Sound Effects CSV file...")
        self.csv_edit.setStyleSheet(
            "background-color: rgba(255, 255, 255, 210); border: 1px solid rgba(160, 180, 200, 150); border-radius: 3px;"
        )
        
        browse_csv_button = QPushButton("Browse...")
        browse_csv_button.setFixedWidth(100)
        browse_csv_button.clicked.connect(self.browse_csv_file)
        browse_csv_button.setStyleSheet(self.get_aero_button_style())
        
        csv_layout.addWidget(csv_label)
        csv_layout.addWidget(self.csv_edit)
        csv_layout.addWidget(browse_csv_button)
        file_layout.addLayout(csv_layout)
        
        # Load button
        load_button = QPushButton("Load Sound Effects")
        load_button.clicked.connect(self.load_csv_data)
        load_button.setStyleSheet(self.get_aero_button_style(True))
        file_layout.addWidget(load_button)
        
        main_layout.addWidget(file_group)
        
        # Settings group
        settings_group = AeroGroupBox("Download Settings")
        settings_layout = QFormLayout(settings_group)
        settings_layout.setContentsMargins(15, 25, 15, 15)
        settings_layout.setSpacing(12)
        
        # Output directory setting
        output_layout = QHBoxLayout()
        self.output_edit = QTextEdit()
        self.output_edit.setFixedHeight(28)
        self.output_edit.setPlainText(str(DEFAULT_OUTPUT_DIR))
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            "background-color: rgba(255, 255, 255, 210); border: 1px solid rgba(160, 180, 200, 150); border-radius: 3px;"
        )
        
        browse_button = QPushButton("Browse...")
        browse_button.setFixedWidth(100)
        browse_button.clicked.connect(self.browse_output_dir)
        browse_button.setStyleSheet(self.get_aero_button_style())
        
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(browse_button)
        settings_layout.addRow(self.create_label("Output Directory:"), output_layout)
        
        # Thread count setting
        self.thread_spinbox = QSpinBox()
        self.thread_spinbox.setRange(1, 20)  # Reduced max threads for stability
        self.thread_spinbox.setValue(DEFAULT_THREAD_COUNT)
        self.thread_spinbox.setFixedWidth(100)
        self.thread_spinbox.setStyleSheet(
            "background-color: rgba(255, 255, 255, 210); border: 1px solid rgba(160, 180, 200, 150); border-radius: 3px;"
        )
        settings_layout.addRow(self.create_label("Download Threads:"), self.thread_spinbox)
        
        # Retry count setting
        self.retry_spinbox = QSpinBox()
        self.retry_spinbox.setRange(1, 10)
        self.retry_spinbox.setValue(DEFAULT_RETRY_COUNT)
        self.retry_spinbox.setFixedWidth(100)
        self.retry_spinbox.setStyleSheet(
            "background-color: rgba(255, 255, 255, 210); border: 1px solid rgba(160, 180, 200, 150); border-radius: 3px;"
        )
        settings_layout.addRow(self.create_label("Retry Attempts:"), self.retry_spinbox)
        
        main_layout.addWidget(settings_group)
        
        # Overall progress
        progress_group = AeroGroupBox("Download Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setContentsMargins(15, 25, 15, 15)
        progress_layout.setSpacing(10)
        
        # Status label
        self.status_label = self.create_label("Please load CSV file to begin")
        progress_layout.addWidget(self.status_label)
        
        # Progress bar
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setValue(0)
        self.total_progress.setTextVisible(True)
        self.total_progress.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid rgba(160, 180, 200, 150);
                border-radius: 3px;
                text-align: center;
                background-color: rgba(255, 255, 255, 180);
                height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #8ccfff, stop:1 #4ca6ff);
                border-radius: 2px;
            }
            """
        )
        progress_layout.addWidget(self.total_progress)
        
        # Current file progress
        current_layout = QHBoxLayout()
        self.current_file_label = self.create_label("No active downloads", "9pt")
        current_layout.addWidget(self.current_file_label)
        
        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 100)
        self.current_progress.setValue(0)
        self.current_progress.setTextVisible(True)
        self.current_progress.setStyleSheet(self.total_progress.styleSheet())
        current_layout.addWidget(self.current_progress)
        progress_layout.addLayout(current_layout)
        
        main_layout.addWidget(progress_group)
        
        # Log view
        log_group = AeroGroupBox("Download Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(15, 25, 15, 15)
        log_layout.setSpacing(10)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            f"font-family: '{AERO_FONT}'; font-size: 9pt; background-color: rgba(255, 255, 255, 180); "
            f"border: 1px solid rgba(160, 180, 200, 150); border-radius: 3px; padding: 3px;"
        )
        log_layout.addWidget(self.log_text)
        
        main_layout.addWidget(log_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start Downloads")
        self.start_button.setEnabled(False)  # Disabled until CSV is loaded
        self.start_button.setStyleSheet(self.get_aero_button_style(True))
        self.start_button.clicked.connect(self.start_downloads)
        
        self.stop_button = QPushButton("Stop Downloads")
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet(self.get_aero_button_style())
        self.stop_button.clicked.connect(self.stop_downloads)
        
        button_layout.addStretch()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        
        main_layout.addLayout(button_layout)
        
        # Footer with Aero Glass-style credits
        footer_frame = AeroFrame()
        footer_layout = QVBoxLayout(footer_frame)
        footer_layout.setContentsMargins(10, 10, 10, 10)
        
        footer_label = QLabel("© 2025 BBC Sound Effects Downloader - Thread Pool Edition")
        footer_label.setStyleSheet(
            f"font-family: '{AERO_FONT}'; font-size: 8pt; color: #555555; background: transparent;"
        )
        footer_label.setAlignment(Qt.AlignCenter)
        footer_layout.addWidget(footer_label)
        
        main_layout.addWidget(footer_frame)
        
        self.setCentralWidget(central_widget)
        
        # Initial log message
        self.log_message("Application started. Please select a CSV file to begin.")
    
    def create_label(self, text, size="10pt"):
        """Create a styled label for Aero Glass look"""
        label = QLabel(text)
        label.setStyleSheet(
            f"font-family: '{AERO_FONT}'; font-size: {size}; color: #333333; "
            f"background: transparent;"
        )
        return label
    
    def get_aero_button_style(self, primary=False):
        """Get Aero Glass button style"""
        if primary:
            # Primary button (blue)
            return f"""
                QPushButton {{
                    font-family: '{AERO_FONT}';
                    font-size: 10pt;
                    color: #ffffff;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                             stop:0 #5aafff, stop:1 #0078d7);
                    border: 1px solid #0067be;
                    border-radius: 4px;
                    padding: 6px 20px;
                    min-height: 25px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                             stop:0 #6cb9ff, stop:1 #0086ef);
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                             stop:0 #0070cc, stop:1 #005799);
                }}
                QPushButton:disabled {{
                    background: #aaaaaa;
                    color: #e0e0e0;
                    border: 1px solid #888888;
                }}
            """
        else:
            # Standard button (light)
            return f"""
                QPushButton {{
                    font-family: '{AERO_FONT}';
                    font-size: 10pt;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                             stop:0 #f8f8f8, stop:1 #e8e8e8);
                    border: 1px solid #acacac;
                    border-radius: 4px;
                    padding: 6px 12px;
                    min-height: 25px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                             stop:0 #eaf6fd, stop:1 #d8f0fa);
                    border: 1px solid #0078d7;
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                             stop:0 #c7e7fa, stop:1 #add8f0);
                }}
                QPushButton:disabled {{
                    background: #f0f0f0;
                    color: #a0a0a0;
                    border: 1px solid #cccccc;
                }}
            """
    
    def apply_aero_style(self):
        """Apply Windows Aero Glass-like styling across platforms"""
        pass  # Most styling is done inline with widgets now
    
    def log_message(self, message):
        """Add a message to the log view"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # Scroll to the bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def browse_csv_file(self):
        """Open file dialog to select CSV file"""
        options = QFileDialog.Options()
        if IS_LINUX:
            # Some Linux desktop environments have issues with native dialogs
            desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
            if desktop in ['kde', 'lxde', 'xfce']:
                options |= QFileDialog.DontUseNativeDialog
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select BBC Sound Effects CSV File", "", 
            "CSV Files (*.csv);;All Files (*)", options=options)
            
        if file_path:
            self.csv_file_path = Path(file_path)
            self.csv_edit.setPlainText(str(file_path))
            self.log_message(f"Selected CSV file: {file_path}")
    
    def load_csv_data(self):
        """Load data from the selected CSV file"""
        if not self.csv_file_path:
            QMessageBox.warning(self, "No CSV File", 
                               "Please select a CSV file first.", QMessageBox.Ok)
            return
        
        if not self.csv_file_path.exists():
            QMessageBox.critical(self, "File Not Found", 
                                f"The file {self.csv_file_path} does not exist.", 
                                QMessageBox.Ok)
            return
        
        try:
            self.samples = []
            found_files = 0
            
            self.log_message(f"Loading sample list from {self.csv_file_path}")
            
            with open(self.csv_file_path, encoding='utf8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Skip if missing required fields
                    if not all(key in row for key in ['CDName', 'description', 'location']):
                        continue
                        
                    folder = self.sanitize_path(row['CDName'])
                    suffix = '.' + row['location']
                    max_description_length = DEFAULT_MAX_FILENAME_LENGTH - len(suffix)
                    filename = self.sanitize_path(row['description'])[:max_description_length] + suffix
                    filepath = self.output_dir / folder / filename
                    
                    # Check if file exists (but only if parent directory exists)
                    should_download = True
                    if filepath.parent.exists() and filepath.exists():
                        found_files += 1
                        should_download = False
                    
                    if should_download:
                        # Use the updated BBC Rewind URL structure
                        # First try the new domain with same path structure
                        url = 'https://sound-effects.bbcrewind.co.uk/assets/' + row['location']
                        
                        # Add fallback URL options in case the structure has changed
                        fallback_urls = [
                            'https://sound-effects.bbcrewind.co.uk/' + row['location'],
                            'http://bbcsfx.acropolis.org.uk/assets/' + row['location']  # Old URL as last resort
                        ]
                        
                        self.samples.append((url, filepath, fallback_urls))
            
            self.total_count = len(self.samples)
            skip_msg = f" (Skipping {found_files} existing files)" if found_files > 0 else ""
            
            if self.total_count > 0:
                self.status_label.setText(f"Found {self.total_count} samples to download{skip_msg}")
                self.log_message(f"Found {self.total_count} samples to download{skip_msg}")
                self.start_button.setEnabled(True)
            else:
                self.status_label.setText(f"No new samples to download{skip_msg}")
                self.log_message(f"No new samples to download{skip_msg}")
                self.start_button.setEnabled(False)
                
        except Exception as e:
            error_msg = f"Failed to load samples: {str(e)}"
            self.log_message(error_msg)
            traceback.print_exc()
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
    
    def browse_output_dir(self):
        """Open file dialog to select output directory"""
        options = QFileDialog.Options()
        if IS_LINUX:
            # Some Linux desktop environments have issues with native dialogs
            desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
            if desktop in ['kde', 'lxde', 'xfce']:
                options |= QFileDialog.DontUseNativeDialog
                
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", str(self.output_dir), options)
            
        if dir_path:
            self.output_dir = Path(dir_path)
            self.output_edit.setPlainText(dir_path)
            self.log_message(f"Output directory changed to: {dir_path}")
            
            # Make sure the new directory exists
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                if IS_LINUX:
                    os.chmod(self.output_dir, 0o755)  # rwxr-xr-x
            except Exception as e:
                self.log_message(f"Warning: Failed to create output directory: {e}")
    
    def sanitize_path(self, path):
        """Sanitize a path string for cross-platform filesystem compatibility"""
        # Remove characters that are problematic on any platform
        sanitized = re.sub(r'[^\w\-&,()\. ]', '_', path).strip()
        
        # Additional Linux/macOS specific handling
        if not IS_WINDOWS:
            # Avoid hidden files (those starting with a dot)
            if sanitized.startswith('.'):
                sanitized = '_' + sanitized
                
        return sanitized
    
    def process_download_queue(self):
        """Process download result queue to update UI"""
        if self.is_shutting_down:
            return
            
        # Process up to 10 results per timer tick
        for _ in range(10):
            try:
                # Non-blocking get with timeout
                item = self.download_results_queue.get(block=False)
                if item:
                    self.handle_download_result(*item)
            except queue.Empty:
                break
            except Exception as e:
                self.log_message(f"Error processing download queue: {str(e)}")
                break
    
    def handle_download_result(self, success, filepath_str, error_msg):
        """Handle a download result from the queue"""
        if self.is_shutting_down:
            return
            
        if success:
            self.finished_count += 1
            self.log_message(f"Download completed: {os.path.basename(filepath_str)}")
        else:
            self.failed_count += 1
            self.log_message(f"Download failed: {os.path.basename(filepath_str)} - {error_msg}")
        
        # Remove from active downloads
        if filepath_str in self.active_downloads:
            del self.active_downloads[filepath_str]
        
        # Update overall progress
        completed = self.finished_count + self.failed_count
        progress_percent = int(completed * 100 / self.total_count) if self.total_count > 0 else 0
        self.total_progress.setValue(progress_percent)
        self.status_label.setText(
            f"Progress: {completed}/{self.total_count} - "
            f"{self.finished_count} completed, {self.failed_count} failed"
        )
        
        # Start more downloads if needed
        self.start_next_downloads()
        
        # Check if all downloads completed
        if not self.active_downloads and completed == self.total_count:
            self.downloads_completed()
    
    def update_download_progress(self, filepath_str, status_text, percent):
        """Update UI for download progress"""
        if self.is_shutting_down:
            return
            
        # Update UI with latest progress
        self.current_file_label.setText(status_text)
        self.current_progress.setValue(percent)
    
    def download_finished(self, success, filepath_str, error_msg):
        """Add download result to queue for processing on main thread"""
        if self.is_shutting_down:
            return
            
        # Add to queue for processing on main thread
        self.download_results_queue.put((success, filepath_str, error_msg))
    
    def start_downloads(self):
        """Start the download process"""
        if not self.samples:
            self.log_message("No samples to download")
            return
        
        # Update UI
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.thread_spinbox.setEnabled(False)
        self.retry_spinbox.setEnabled(False)
        
        # Reset counters
        self.finished_count = 0
        self.failed_count = 0
        self.total_progress.setValue(0)
        self.active_downloads = {}
        
        # Ensure the thread pool has the right max thread count
        self.thread_pool.setMaxThreadCount(self.thread_spinbox.value())
        
        # Ensure the output directory exists before starting downloads
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            if IS_LINUX:
                os.chmod(self.output_dir, 0o755)  # rwxr-xr-x
        except Exception as e:
            error_msg = f"Error creating output directory: {str(e)}"
            self.log_message(error_msg)
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            
            # Reset UI
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.thread_spinbox.setEnabled(True)
            self.retry_spinbox.setEnabled(True)
            return
        
        # Start downloads
        self.log_message(f"Starting downloads with up to {self.thread_spinbox.value()} threads")
        self.status_label.setText(f"Downloading {self.total_count} samples...")
        
        # Start initial batch of downloads
        self.start_next_downloads()
    
    def start_next_downloads(self):
        """Start as many downloads as needed to keep thread pool busy"""
        if self.is_shutting_down:
            return
            
        # How many more threads can we use?
        available_threads = self.thread_spinbox.value() - len(self.active_downloads)
        
        # Start more downloads if needed
        for _ in range(min(available_threads, len(self.samples))):
            # Don't start new downloads if shutting down
            if self.is_shutting_down:
                return
                
            # Get next sample
            if not self.samples:
                break
                
            url, filepath, fallback_urls = self.samples.pop(0)
            filepath_str = str(filepath)
            
            # Create worker
            worker = DownloadWorker(
                url, filepath, 
                fallback_urls=fallback_urls,
                retry_count=self.retry_spinbox.value()
            )
            
            # Connect signals - using lambda to capture filepath_str for the signal connection
            worker.signals.progress.connect(self.update_download_progress)
            worker.signals.finished.connect(self.download_finished)
            
            # Store reference to track active downloads
            self.active_downloads[filepath_str] = worker
            
            # Start download
            self.log_message(f"Starting download: {filepath.name} from {url.split('/')[2]}")
            self.thread_pool.start(worker)
    
    def downloads_completed(self):
        """Handle completion of all downloads"""
        if self.is_shutting_down:
            return
            
        self.log_message(f"All downloads completed: {self.finished_count} successful, {self.failed_count} failed")
        self.status_label.setText(
            f"Completed: {self.finished_count} successful, {self.failed_count} failed"
        )
        
        # Reset UI
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.thread_spinbox.setEnabled(True)
        self.retry_spinbox.setEnabled(True)
        self.current_file_label.setText("No active downloads")
        self.current_progress.setValue(0)
        
        # Show completion message
        if self.finished_count > 0:
            if self.failed_count == 0:
                QMessageBox.information(
                    self, "Downloads Complete", 
                    f"All {self.finished_count} downloads completed successfully.",
                    QMessageBox.Ok
                )
            else:
                QMessageBox.warning(
                    self, "Downloads Complete",
                    f"Downloads completed with {self.failed_count} failures.\n"
                    f"{self.finished_count} files were downloaded successfully.",
                    QMessageBox.Ok
                )
    
    def stop_downloads(self):
        """Stop all active downloads"""
        reply = QMessageBox.question(
            self, "Confirm Stop",
            "Are you sure you want to stop all downloads?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.log_message("Stopping all downloads...")
            
            # Set cancellation flag on all workers
            for filepath_str, worker in list(self.active_downloads.items()):
                try:
                    worker.is_cancelled = True
                except:
                    pass
            
            # Clear the download queue
            self.samples.clear()
            
            # Reset UI
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.thread_spinbox.setEnabled(True)
            self.retry_spinbox.setEnabled(True)
            self.current_file_label.setText("Downloads stopped")
            
            self.log_message("All downloads stopped")
            self.status_label.setText(
                f"Stopped: {self.finished_count} completed, "
                f"{len(self.active_downloads)} cancelled"
            )
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Set shutting down flag immediately
        self.is_shutting_down = True
        
        if self.active_downloads:
            reply = QMessageBox.question(
                self, "Confirm Exit",
                "Downloads are still in progress. Are you sure you want to exit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Cancel all active downloads
                for _, worker in list(self.active_downloads.items()):
                    try:
                        worker.is_cancelled = True
                    except:
                        pass
                
                # Wait briefly to ensure threads have a chance to respond to cancellation
                QTimer.singleShot(200, QApplication.quit)
                event.accept()
            else:
                # Reset shutting down flag and reject close
                self.is_shutting_down = False
                event.ignore()
        else:
            event.accept()


def excepthook(exc_type, exc_value, exc_traceback):
    """Global exception handler to log unhandled exceptions"""
    print("Unhandled exception:")
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    QMessageBox.critical(
        None, 
        "Error", 
        f"An unhandled exception occurred:\n{str(exc_value)}\n\n"
        f"The application will now close.",
        QMessageBox.Ok
    )


def main():
    # Set up global exception handler
    sys.excepthook = excepthook
    
    # Create QApplication
    app = QApplication(sys.argv)
    
    # Enable High DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # Use platform-specific styling
    if IS_WINDOWS:
        # Try to use Aero style on Windows
        if "WindowsVista" in QStyleFactory.keys():
            app.setStyle(QStyleFactory.create("WindowsVista"))
    elif IS_LINUX:
        # Try to use a style that works well on Linux
        if "Fusion" in QStyleFactory.keys():
            app.setStyle(QStyleFactory.create("Fusion"))
    elif IS_MAC:
        # On macOS, use the native style
        pass
    
    # Create and show the main window
    window = BBCSoundDownloaderGUI()
    window.show()
    
    # Run the application
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
