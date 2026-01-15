# 🚀 Rumble Content Manager

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Tkinter](https://img.shields.io/badge/GUI-Tkinter-green?logo=python)
![Selenium](https://img.shields.io/badge/Automation-Selenium-orange?logo=selenium)

**Rumble Content Manager** is a powerful, multithreaded desktop application designed to help creators manage their Rumble video library efficiently. It solves the problem of slow, manual video deletion by automating the process with a clean, responsive GUI.

Unlike basic scrapers, this tool uses a **"Search & Destroy"** architecture to maintain stability even when scanning thousands of videos, avoiding UI freezes and memory crashes.

---

## ✨ Features

* **🔐 Automated Login:** Handles login once and saves session cookies for future runs.
* **🔎 "Search & Destroy" Scanning:** Filters videos by title *during* the scan process. This saves memory by only rendering relevant videos (e.g., finding all videos with "Test" in the title).
* **🖼️ Visual Interface:** Displays video thumbnails, titles, and sequential IDs in a scrollable, zoomable list.
* **⚡ Synchronous & Stable:** Uses a specialized blocking scan logic to ensure pages load in strict order (Page 1 → Page 2) without crashing the interface.
* **🧹 Multi-Threaded Deletion:** Spin up multiple workers (e.g., 4, 8, 10 threads) to delete selected videos rapidly in parallel.
* **🛡️ Overlay Handling:** Automatically detects and confirms Rumble's custom javascript delete confirmation overlays.

---

## 🛠️ Installation

### Prerequisites
1.  **Python 3.10+** installed.
2.  **Google Chrome** installed (required for `undetected_chromedriver`).

### Setup
1.  Clone this repository:
    ```bash
    git clone [https://github.com/YourUsername/rumble-content-manager.git](https://github.com/YourUsername/rumble-content-manager.git)
    cd rumble-content-manager
    ```

2.  Install required dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *(If you don't have a requirements file, install these packages manually)*:
    ```bash
    pip install undetected-chromedriver selenium beautifulsoup4 pillow requests pyinstaller
    ```

---

## 📖 Usage Guide

### 1. Login
* Click the **Login** button.
* A browser window will open. Log in to your Rumble account manually.
* Once logged in, the window will close automatically, and your session cookies will be saved to `rumble_cookies.pkl`.

### 2. Scanning Content
* **Set Page Range:** Choose how deep you want to scan (e.g., Page 1 to 50).
* **Set Filter (Optional):** Enter a keyword in the **"Title Contains"** box (e.g., `stream`).
    * *Tip:* If you enter a keyword, the app will **only** load videos matching that title. This is much faster and uses less RAM than loading everything.
* **Click SERIAL SCAN:** The app will scrape pages one by one, downloading thumbnails and populating the list in real-time.

### 3. Deleting Videos
* **Select Videos:** Use the checkboxes to select items or click **Select All**.
* **Set Workers:** Choose how many browser instances to use for deletion (default is 4).
* **Click DELETE SELECTED:** The app will open invisible browsers, navigate to each video, and confirm deletion. Rows will turn **Red** when successfully deleted.

---

## 🧠 How it Works

The application uses a **Hybrid Architecture**:
1.  **Scanning is Serial (Single Thread):** To prevent UI floods and ensure videos appear in the correct order (Newest first), scanning happens one page at a time.
2.  **Deletion is Parallel (Multi-Thread):** Deletion is an independent task, so we spawn multiple workers to clear the queue as fast as possible.

### Sequence Diagram

```mermaid
sequenceDiagram
    participant User
    participant GUI as 🖥️ GUI (Main Thread)
    participant Scanner as 🕷️ Scan Worker
    participant Rumble as ☁️ Rumble.com
    participant Deleter as 🗑️ Delete Workers

    User->>GUI: Enter "Minecraft" & Click SCAN
    GUI->>Scanner: Start Serial Scan (Pg 1-10)
    
    loop For Each Page
        Scanner->>Rumble: GET /account/content?pg=X
        Rumble-->>Scanner: Return HTML
        Scanner->>Scanner: Parse & Filter by Title "Minecraft"
        
        opt Match Found
            Scanner->>Rumble: Download Thumbnail (Blocking)
            Scanner->>GUI: Push Data Batch
            GUI->>GUI: Render Rows w/ Images
        end
    end

    User->>GUI: Select Videos & Click DELETE
    GUI->>Deleter: Spawn 4 Workers w/ Queue
    
    par Parallel Deletion
        Deleter->>Rumble: Navigate to Video Page
        Deleter->>Rumble: Click Menu -> Delete
        Deleter->>Rumble: Detect & Click Overlay Confirm
        Deleter-->>GUI: Update Row Color (Red)
    end
