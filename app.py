import sys
import os
import threading
import queue
import time
import pickle
import requests
import re
from io import BytesIO
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageTk
import multiprocessing

if sys.version_info >= (3, 12):
    try:
        import setuptools
    except ImportError:
        pass

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- FILES ---
COOKIES_FILE = "rumble_cookies.pkl"


def get_sequential_id(url):
    try:
        match = re.search(r'/v([a-z0-9]+)[-.]', url)
        if match:
            code = match.group(1)
            return int(code, 36)
    except:
        pass
    return 0


class VideoRow:
    """
    Optimized Row: Frame -> [Checkbox] [Thumb] [TextLabel]
    """

    def __init__(self, parent, data, controller):
        self.data = data
        self.controller = controller
        self.var = tk.BooleanVar()
        self.original_img = None

        h = int(65 * controller.ui_scale)

        self.frame = tk.Frame(parent, bg="white", bd=1, relief="solid", height=h)
        self.frame.grid_propagate(False)
        self.frame.columnconfigure(2, weight=1)

        # 1. Checkbox
        self.chk = tk.Checkbutton(self.frame, variable=self.var, bg="white")
        self.chk.grid(row=0, column=0, rowspan=2, padx=2, sticky="ns")

        # 2. Thumbnail
        self.thumb_label = tk.Label(self.frame, bg="#eee", width=12, text="...")
        self.thumb_label.grid(row=0, column=1, rowspan=2, padx=2, pady=1)

        # 3. Text Info
        full_text = f"[Pg {data['page']}]  {data['title'][:90]}\nID: {data['seq_id']} | {data['url']}"
        self.text_label = tk.Label(self.frame, text=full_text, bg="white", anchor="w", justify="left")
        self.text_label.grid(row=0, column=2, sticky="nsew", padx=5)

        # Image Load
        if self.data.get('img_bytes'):
            try:
                self.original_img = Image.open(BytesIO(self.data['img_bytes']))
            except:
                pass

        self.apply_scale(self.controller.ui_scale)

    def apply_scale(self, scale):
        row_h = int(65 * scale)
        self.frame.config(height=row_h)
        title_size = int(10 * scale)
        self.text_label.config(font=("Arial", title_size))

        if self.original_img:
            try:
                w, h = int(100 * scale), int(60 * scale)
                resized = self.original_img.resize((w, h), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(resized)
                self.thumb_label.config(image=self.photo, text="", width=0, height=0)
            except:
                pass
        else:
            self.thumb_label.config(text="No Img")

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def destroy(self):
        self.frame.destroy()


class RumbleContentManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Rumble Manager - Search & Destroy")
        self.root.geometry("1200x850")

        self.is_running = False
        self.drivers = []
        self.video_rows = []
        self.delete_queue = queue.Queue()

        self.log_lock = threading.Lock()
        self.driver_lock = threading.Lock()

        self.ui_scale = 1.0
        self.seen_ids = set()

        self.row_limit = 2000

        self._setup_ui()
        self.root.bind("<Control-MouseWheel>", self.zoom_ui)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_ui(self):
        # --- Top Controls ---
        control_frame = tk.LabelFrame(self.root, text="1. Search Settings", padx=10, pady=5)
        control_frame.pack(fill="x", padx=10, pady=5)

        tk.Button(control_frame, text="Login", command=self.perform_login, bg="#e1f5fe").pack(side="left", padx=5)

        tk.Label(control_frame, text="|  Search Pages 1 to:").pack(side="left", padx=(10, 2))
        self.spin_pages = tk.Spinbox(control_frame, from_=1, to=1000, width=5)
        self.spin_pages.delete(0, "end")
        self.spin_pages.insert(0, 50)
        self.spin_pages.pack(side="left")

        tk.Label(control_frame, text="Title Contains:").pack(side="left", padx=(15, 2))
        self.entry_search = tk.Entry(control_frame, width=25, bg="#fff9c4")
        self.entry_search.pack(side="left", padx=5)

        self.btn_scan = tk.Button(control_frame, text="START SEARCH", command=self.start_scan, bg="#c8e6c9",
                                  font=("Arial", 10, "bold"))
        self.btn_scan.pack(side="left", padx=15)

        self.headless_var = tk.BooleanVar(value=True)
        tk.Checkbutton(control_frame, text="Headless", variable=self.headless_var).pack(side="right", padx=5)

        # --- Middle Actions ---
        action_frame = tk.Frame(self.root)
        action_frame.pack(fill="x", padx=10, pady=(5, 0))

        tk.Button(action_frame, text="Select All", command=self.select_all).pack(side="left", padx=5)
        tk.Button(action_frame, text="Deselect All", command=self.deselect_all).pack(side="left", padx=5)

        tk.Label(action_frame, text="Delete Workers:").pack(side="right")
        self.spin_threads = tk.Spinbox(action_frame, from_=1, to=10, width=3)
        self.spin_threads.pack(side="right", padx=5)
        self.spin_threads.delete(0, "end")
        self.spin_threads.insert(0, 4)

        tk.Button(action_frame, text="DELETE SELECTED", command=self.start_delete_process, bg="#ffcdd2", fg="red",
                  font=("Arial", 9, "bold")).pack(side="right", padx=10)

        # --- Content List ---
        list_frame = tk.LabelFrame(self.root, text="Search Results", padx=5, pady=5)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas = tk.Canvas(list_frame, bg="white")
        self.scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="white")

        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # --- Logs ---
        log_frame = tk.LabelFrame(self.root, text="Logs", padx=5, pady=5)
        log_frame.pack(fill="x", padx=10, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, state='disabled', height=8, font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if not (event.state & 0x0004):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def zoom_ui(self, event):
        self.ui_scale = max(0.5, min(self.ui_scale + (0.1 if event.delta > 0 else -0.1), 2.0))
        for row in self.video_rows: row.apply_scale(self.ui_scale)

    def log(self, message):
        print(message)
        with self.log_lock:
            self.log_area.config(state='normal')
            self.log_area.insert(tk.END, f"{message}\n")
            self.log_area.see(tk.END)
            self.log_area.config(state='disabled')

    # --- DRIVER ---
    def get_driver(self, headless=False):
        with self.driver_lock:
            options = uc.ChromeOptions()
            if headless: options.add_argument("--headless=new")
            options.add_argument("--start-maximized")
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--blink-settings=imagesEnabled=false")
            options.page_load_strategy = 'eager'
            return uc.Chrome(options=options)

    def perform_login(self):
        threading.Thread(target=self._login_process, daemon=True).start()

    def _login_process(self):
        self.log("Opening login browser...")
        driver = self.get_driver(headless=False)
        try:
            driver.get("https://rumble.com/login.php")
            self.log("Waiting 60s for login...")
            start = time.time()
            while time.time() - start < 60:
                if driver.get_cookie("u_s"):
                    pickle.dump(driver.get_cookies(), open(COOKIES_FILE, "wb"))
                    self.log("Cookies saved!")
                    break
                time.sleep(1)
        finally:
            driver.quit()

    def clear_list(self):
        for row in self.video_rows: row.destroy()
        self.video_rows.clear()
        self.seen_ids.clear()
        self.canvas.yview_moveto(0)

    def select_all(self):
        for r in self.video_rows: r.var.set(True)

    def deselect_all(self):
        for r in self.video_rows: r.var.set(False)

    # --- SCANNER ---
    def start_scan(self):
        if not os.path.exists(COOKIES_FILE): return messagebox.showerror("Error", "Login first.")

        try:
            max_pg = int(self.spin_pages.get())
        except:
            max_pg = 10

        search_term = self.entry_search.get().strip().lower()

        if not search_term:
            if not messagebox.askyesno("Warning",
                                       "Search filter is empty. This will load ALL videos and may be slow. Continue?"):
                return

        self.clear_list()
        self.is_running = True
        self.log(f"Starting Search for '{search_term}' in {max_pg} pages...")
        threading.Thread(target=self._search_logic, args=(max_pg, search_term), daemon=True).start()

    def _search_logic(self, max_pages, search_term):
        headless = self.headless_var.get()
        driver = None
        try:
            driver = self.get_driver(headless=headless)
            driver.get("https://rumble.com/404")
            for c in pickle.load(open(COOKIES_FILE, "rb")):
                try:
                    driver.add_cookie(c)
                except:
                    pass

            self.drivers.append(driver)

            for page_num in range(1, max_pages + 1):
                if not self.is_running: break
                if len(self.video_rows) >= self.row_limit:
                    self.log(f"!!! Result Limit ({self.row_limit}) Reached. Stopping.")
                    break

                self.log(f"--- Scanning Page {page_num} ---")

                try:
                    driver.get(f"https://rumble.com/account/content?pg={page_num}")
                    try:
                        WebDriverWait(driver, 8).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".content-page-box")))
                    except:
                        self.log(f"Page {page_num} timed out or empty.")
                        continue

                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    items = soup.select(".info-video")

                    if not items:
                        self.log(f"No items on Page {page_num}")
                        continue

                    batch_data = []
                    matches_on_page = 0

                    for item in items:
                        title_el = item.select_one(".video-title a")
                        title = title_el.get_text(strip=True) if title_el else "Unknown"

                        if search_term and search_term not in title.lower():
                            continue

                        matches_on_page += 1

                        link_el = item.select_one("a.video-thumbnail")
                        if not link_el: continue
                        url = "https://rumble.com" + link_el['href']
                        seq_id = get_sequential_id(url)

                        thumb_url = link_el.find("img")['src'] if link_el.find("img") else None

                        data = {
                            "title": title, "url": url, "thumb_url": thumb_url,
                            "page": page_num, "video_id": url.split("/")[-1],
                            "html_id": item.get('id'), "seq_id": seq_id,
                            "img_bytes": None
                        }
                        batch_data.append(data)

                    if batch_data:
                        self.log(f"Found {matches_on_page} matches. Downloading images...")
                        for v in batch_data:
                            if not self.is_running: break
                            if v['thumb_url']:
                                try:
                                    t_url = v['thumb_url']
                                    if t_url.startswith("//"): t_url = "https:" + t_url
                                    resp = requests.get(t_url, timeout=5)
                                    if resp.status_code == 200:
                                        v['img_bytes'] = resp.content
                                except:
                                    pass

                        if self.is_running:
                            self.root.after(0, lambda d=batch_data: self._add_batch_to_gui(d))
                            time.sleep(0.3)
                    else:
                        self.log(f"No matches on Page {page_num}.")

                except Exception as e:
                    self.log(f"Error on Page {page_num}: {e}")

        except Exception as e:
            self.log(f"Scanner Crash: {e}")
        finally:
            if driver: driver.quit()
            self.log("Search Finished.")

    def _add_batch_to_gui(self, video_list):
        video_list.sort(key=lambda x: x['seq_id'], reverse=True)
        count = 0
        for v in video_list:
            if v['seq_id'] not in self.seen_ids:
                if len(self.video_rows) >= self.row_limit: break
                self.seen_ids.add(v['seq_id'])
                row = VideoRow(self.scrollable_frame, v, self)
                row.pack(fill="x", pady=1)
                self.video_rows.append(row)
                count += 1

        if count > 0:
            self.canvas.update_idletasks()

    # --- DELETE ---
    def start_delete_process(self):
        selected = [r for r in self.video_rows if r.var.get()]
        if not selected: return messagebox.showinfo("Info", "None selected.")
        if not messagebox.askyesno("CONFIRM", f"Delete {len(selected)} videos?"): return

        try:
            num_workers = int(self.spin_threads.get())
        except:
            num_workers = 2

        self.log(f"Starting Delete with {num_workers} workers...")

        with self.delete_queue.mutex:
            self.delete_queue.queue.clear()
        for row in selected: self.delete_queue.put(row.data)

        self.is_running = True
        threading.Thread(target=self._init_delete_workers, args=(num_workers,), daemon=True).start()

    def _init_delete_workers(self, num_workers):
        active_drivers = []
        for i in range(num_workers):
            try:
                d = self.get_driver(headless=self.headless_var.get())
                d.get("https://rumble.com/404")
                for c in pickle.load(open(COOKIES_FILE, "rb")):
                    try:
                        d.add_cookie(c)
                    except:
                        pass
                active_drivers.append(d)
                self.drivers.append(d)
            except:
                pass

        threads = []
        for i, driver in enumerate(active_drivers):
            t = threading.Thread(target=self._delete_worker_task, args=(driver,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads: t.join()

        for d in active_drivers:
            try:
                d.quit()
            except:
                pass
        self.log("Delete Sequence Complete.")

    def _delete_worker_task(self, driver):
        while not self.delete_queue.empty() and self.is_running:
            try:
                data = self.delete_queue.get(timeout=1)
                self._delete_single_video(driver, data)
            except:
                break

    def _delete_single_video(self, driver, data):
        self.log(f"Deleting: {data['title'][:30]}...")
        try:
            driver.get(f"https://rumble.com/account/content?pg={data['page']}")

            target = None
            if data.get('html_id'):
                try:
                    target = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, data['html_id'])))
                except:
                    pass

            if not target:
                rel_url = data['url'].replace("https://rumble.com", "")
                xpath = f"//div[contains(@class, 'info-video')]//a[@href='{rel_url}']/ancestor::div[contains(@class, 'info-video')]"
                target = driver.find_element(By.XPATH, xpath)

            menu = target.find_element(By.CSS_SELECTOR, ".open-menu")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", menu)

            del_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".dd-menu[style*='block'] a#delete")))
            driver.execute_script("arguments[0].click();", del_btn)

            try:
                self.log(" -> Waiting for confirmation popup...")
                confirm_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".overlay-dialog .buttons a[id='0']"))
                )
                driver.execute_script("arguments[0].click();", confirm_btn)
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, ".overlay-dialog"))
                )
            except Exception as e:
                self.log(f" -> Confirmation failed: {e}")
                return

            self.root.after(0, lambda: self._mark_deleted(data['url']))
        except Exception as e:
            self.log(f"Delete Fail: {e}")

    def _mark_deleted(self, url):
        for row in self.video_rows:
            if row.data['url'] == url:
                row.chk.config(state="disabled")
                row.frame.config(bg="#ffebee")

    def on_close(self):
        self.is_running = False
        for d in self.drivers:
            try:
                d.quit()
            except:
                pass
        self.root.destroy()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = RumbleContentManager(root)
    root.mainloop()