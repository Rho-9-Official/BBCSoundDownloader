# BBC Sound Effects Downloader - Thread Pool Edition

A cross-platform application to download sound effects from the BBC Sound Effects library with enhanced multi-threading, modern UI, and robust error handling.



## About This Fork

This is a fork of [FThompson's BBCSoundDownloader](https://github.com/FThompson/BBCSoundDownloader) which hasn't been updated in 7 years. The original project was excellent but needed modernization for current BBC URL structures and improved performance for large download sets.

## Key Improvements

- **Modern Thread Pool Architecture**: Complete rewrite using QThreadPool for better concurrency management and lower resource usage
- **Enhanced UI with Aero Glass-like styling**: Beautiful, responsive interface styled consistently across all platforms
- **Cross-Platform Compatibility**: Thoroughly tested and optimized for Windows, macOS, and Linux
- **Updated BBC URL Support**: Works with the current BBC Sound Effects URL structure (bbcrewind.co.uk)
- **Intelligent Fallback System**: Automatically tries alternative URLs if primary download fails
- **Improved File Handling**: Robust handling of path sanitization and file permissions
- **Better Error Recovery**: Exponential backoff for retries and comprehensive error reporting
- **Progress Reporting**: Detailed progress tracking both per file and overall
- **User-Configurable Settings**: Adjustable thread count and retry attempts

## Requirements

- Python 3.6+
- PyQt5
- Internet connection
- BBC Sound Effects CSV file (see Usage section)

## Installation

### Option 1: Using pip
```bash
pip install bbcsounddownloader-threadpool
```

### Option 2: From source
```bash
git clone https://github.com/yourusername/BBCSoundDownloader-ThreadPool.git
cd BBCSoundDownloader-ThreadPool
pip install -r requirements.txt
python main.py
```

## Usage

1. Download the BBC Sound Effects CSV file from the [BBC Sound Effects website](https://sound-effects.bbcrewind.co.uk/)
2. Launch the application
3. Click "Browse..." to select the CSV file
4. Click "Load Sound Effects" to analyze the CSV
5. Adjust settings if needed:
   - Output Directory: Where to save the downloaded files
   - Download Threads: Number of simultaneous downloads (default: 5)
   - Retry Attempts: Number of times to retry failed downloads (default: 3)
6. Click "Start Downloads" to begin
7. Monitor progress in the Download Log section

## Features

### Thread Pool Management
The application uses QThreadPool to manage download threads, providing better performance and resource utilization than the original version. The number of concurrent downloads can be configured through the UI.

### Intelligent URL Handling
The application automatically tries multiple URL patterns in case the primary one fails, ensuring compatibility with different BBC Sound Effects hosting structures.

### Robust Error Handling
- Connection errors are managed with exponential backoff
- Platform-specific file path sanitization
- Appropriate file permissions on Unix systems
- Detailed error logging

### User Interface
- Real-time progress reporting
- Per-file and overall download status
- Detailed logging with timestamps
- Clean, modern design with Aero Glass-inspired styling
- Responsive layout that works well on all screen sizes

## Platform-Specific Notes

### Windows
- Maximum filename length is set to 255 characters (NTFS limit)
- Default output directory is `%USERPROFILE%\Documents\BBCSounds`

### macOS
- Maximum filename length is set to 255 characters (APFS/HFS+ limit)
- Default output directory is `~/Music/BBCSounds`

### Linux
- Maximum filename length is set to 143 characters (conservative for all Linux filesystems)
- Default output directory is `~/BBCSounds`
- File permissions are set to 644 (rw-r--r--) for downloaded files and 755 (rwxr-xr-x) for directories

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the same terms as the original - see the LICENSE file for details.

## Acknowledgments

- Original project by [FThompson](https://github.com/FThompson/BBCSoundDownloader)
- BBC for providing the sound effects library
- The PyQt team for their excellent framework


