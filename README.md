# dcinsideImageCrawler - DCInside Image Downloader & Bot Sender

**dcinsideImageCrawler** is a tool that scrapes images from posts on **DCInside** and automatically sends them to **Discord** and **Telegram** bots. The tool is designed to run on a cloud server like **Oracle Cloud** and **Amazon Web Services**, where it downloads images from DCInside posts and sends them to designated chat channels via bots.

## Features

- Scrapes images from DCInside posts and automatically downloads them.
- Sends the downloaded images to Discord and Telegram bots.
- Works seamlessly on cloud environments like Oracle Cloud.
- Supports multiple image formats and ensures they are properly handled.

## Installation

### Prerequisites

Before setting up DCImg, ensure you have the following installed on your machine or server:

- Python 3.x
- **Discord Bot Token** (for Discord bot integration)
- **Telegram Bot Token** (for Telegram bot integration)
- `pip` (Python's package installer)

### Steps to Install

1. Clone the repository:
   ```bash
   git clone https://github.com/mytrashcan/dcimg.git
   ```
   
2. Navigate to the project directory:
   ```bash
   cd dcimg
   ```

3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. (Optional) Set up a virtual environment to manage dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # For Linux/MacOS
   ```
   
5. Set up environment variables for the bot tokens:  
   Create a ```.env``` file and add the following lines:
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   TELEGRAM_TOKEN=your_telegram_bot_token
   ```

## Usage
The script manages and runs multiple crawling processes that fetch images from DCInside posts. These crawling processes are handled sequentially, with a set maximum number of processes running at any given time.

## Key Features:
- **Process Management**: Limits the number of concurrently running processes (```MAX_PROCESSES```), which helps avoid overloading the system.
- **Circular Queue**: The program cycles through the list of folders, ensuring each folder is processed and revisited after completing the set number of processes.
- **Process Lifetime Management**: Ensures that each process has a maximum runtime (```MAX_PROCESS_LIFETIME```). Once a process reaches this time limit, it is terminated and replaced by a new one.
  
## Running the Script

1. Script Overview: The script continuously manages processes that run a script (```launcher.py```) from multiple folders. If a script is already running for a folder, it will skip that folder.
2. Run the script:
   To run the main process management system, simply execute the following command:
   ```bash
   python launcher.py
   ```
3. Example Usage:
The script will automatically:
- Check if any process for a folder is already running.
- Run the ```launcher.py``` script for folders in a circular queue (up to ```MAX_PROCESSES```).
- Terminate any running processes after the set lifetime (```MAX_PROCESS_LIFETIME```).

4. Execution Flow:
- The script first checks for the running status of all folders.
- If a folder's script is not running, it starts a new process for it.
- Processes are stopped after ```MAX_PROCESS_LIFETIME``` seconds, and the queue restarts.

## License
This project is licensed under the GPL License
