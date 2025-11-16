import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, simpledialog
import multiprocessing as mp
from multiprocessing import Pool, Manager
import queue
import threading
from functools import partial
import mimetypes

# Define file type categories (extensible)
FILE_TYPE_CATEGORIES = {
    "Audio Files": ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.ape', '.alac'],
    "Video Files": ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpg', '.mpeg', '.rmvb', '.3gp'],
    "Image Files": ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg', '.psd', '.ai'],
    "Document Files": ['.doc', '.docx', '.pdf', '.txt', '.xls', '.xlsx', '.ppt', '.pptx', '.md', '.rtf'],
    "Compressed Files": ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
    "Program Files": ['.exe', '.dll', '.py', '.java', '.c', '.cpp', '.js', '.html', '.css']
}

class FileSearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("File Smart Search Tool")
        self.root.geometry("1200x700")
        self.root.minsize(1000, 600)
        
        # Set Chinese font
        self.style = ttk.Style()
        self.style.configure(".", font=("SimHei", 10))
        
        # Search parameters
        self.search_path = tk.StringVar()
        self.keyword = tk.StringVar()
        self.search_type = tk.StringVar(value="name")  # name or content
        self.is_searching = False
        self.manager = Manager()  # For creating cross-process shared objects
        self.stop_event = self.manager.Event()  # Use Manager to create Event
        
        # File type filter status (changed to: only search selected types)
        self.category_vars = {}  # Store category check status
        self.extension_vars = {}  # Store extension check status
        self.included_extensions = set()  # Currently selected extensions to include
        self.other_files_frame = None  # Store frame for "Other Files" category extensions
        
        # Create UI
        self.create_widgets()
        # Initialize file type filter status (no types selected by default)
        self.init_file_type_filters()
        
        # Processes and queues
        self.progress_queue = None
        self.result_queue = None
        self.search_process = None
        
        # Search statistics
        self.total_files = 0
        self.processed_files = 0
        self.matched_files = 0

    def create_widgets(self):
        # Main frame divided into left and right parts
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left: File type filter panel (function changed to only search selected types)
        filter_frame = ttk.LabelFrame(main_paned, text="File Type Filter (Only search selected types)", padding="10")
        main_paned.add(filter_frame, weight=1)
        
        # Filter panel scroll area - defined as class attribute
        self.filter_canvas = tk.Canvas(filter_frame)
        self.filter_scrollbar = ttk.Scrollbar(filter_frame, orient="vertical", command=self.filter_canvas.yview)
        self.filter_scrollable_frame = ttk.Frame(self.filter_canvas)
        
        self.filter_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.filter_canvas.configure(scrollregion=self.filter_canvas.bbox("all"))
        )
        
        self.filter_canvas.create_window((0, 0), window=self.filter_scrollable_frame, anchor="nw")
        self.filter_canvas.configure(yscrollcommand=self.filter_scrollbar.set)
        
        self.filter_canvas.pack(side="left", fill="both", expand=True)
        self.filter_scrollbar.pack(side="right", fill="y")
        
        # Add file type categories and extension checkboxes
        for category, extensions in FILE_TYPE_CATEGORIES.items():
            # Category main checkbox
            cat_var = tk.BooleanVar()
            self.category_vars[category] = cat_var
            cat_check = ttk.Checkbutton(
                self.filter_scrollable_frame, 
                text=category, 
                variable=cat_var,
                command=partial(self.toggle_category, category)
            )
            cat_check.pack(anchor=tk.W, pady=5)
            
            # Extension checkboxes under this category
            ext_frame = ttk.Frame(self.filter_scrollable_frame)
            ext_frame.pack(anchor=tk.W, padx=20)
            
            for ext in extensions:
                ext_var = tk.BooleanVar()
                self.extension_vars[ext] = ext_var
                ext_check = ttk.Checkbutton(
                    ext_frame, 
                    text=ext, 
                    variable=ext_var,
                    command=partial(self.update_category_state, category)
                )
                ext_check.pack(side=tk.LEFT, padx=5, pady=2)
        
        # Add custom extension button
        ttk.Button(
            filter_frame, 
            text="Add Custom Extension", 
            command=self.add_custom_extension
        ).pack(pady=10, fill=tk.X)
        
        # Right: Main function area
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=3)
        
        # Top frame - Path selection
        path_frame = ttk.Frame(right_frame, padding="10")
        path_frame.pack(fill=tk.X)
        
        ttk.Label(path_frame, text="Search Path:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(path_frame, textvariable=self.search_path, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(path_frame, text="Browse...", command=self.browse_path).pack(side=tk.LEFT, padx=5)
        
        # Middle frame - Search settings
        search_frame = ttk.Frame(right_frame, padding="10")
        search_frame.pack(fill=tk.X)
        
        ttk.Label(search_frame, text="Search Keyword:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(search_frame, textvariable=self.keyword, width=30).pack(side=tk.LEFT, padx=5)
        
        ttk.Radiobutton(search_frame, text="By Filename", variable=self.search_type, value="name").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(search_frame, text="By File Content", variable=self.search_type, value="content").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(search_frame, text="Start Search", command=self.start_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(search_frame, text="Stop Search", command=self.stop_search).pack(side=tk.LEFT, padx=5)
        
        # Progress frame
        progress_frame = ttk.Frame(right_frame, padding="10")
        progress_frame.pack(fill=tk.X)
        
        ttk.Label(progress_frame, text="Overall Progress:").pack(side=tk.LEFT, padx=5)
        self.overall_progress = ttk.Progressbar(progress_frame, orient="horizontal", length=100, mode="determinate")
        self.overall_progress.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Stage progress frame
        stage_frame = ttk.Frame(right_frame, padding="10")
        stage_frame.pack(fill=tk.X)
        
        ttk.Label(stage_frame, text="Current Stage:").pack(side=tk.LEFT, padx=5)
        self.stage_label = ttk.Label(stage_frame, text="Ready")
        self.stage_label.pack(side=tk.LEFT, padx=5)
        
        self.stage_progress = ttk.Progressbar(stage_frame, orient="horizontal", length=100, mode="determinate")
        self.stage_progress.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Status frame
        status_frame = ttk.Frame(right_frame, padding="10")
        status_frame.pack(fill=tk.X)
        
        self.status_label = ttk.Label(status_frame, text="Waiting to start search...")
        self.status_label.pack(anchor=tk.W)
        
        # Results frame
        result_frame = ttk.LabelFrame(right_frame, text="Search Results", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        self.result_display = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD)
        self.result_display.pack(fill=tk.BOTH, expand=True, pady=5)
        # Configure style tags for different contents
        self.result_display.tag_configure("filename", foreground="blue", font=("SimHei", 10, "bold"))
        self.result_display.tag_configure("linenum", foreground="green", font=("SimHei", 10))
        self.result_display.tag_configure("match", background="yellow")
        self.result_display.tag_configure("separator", foreground="gray")
        
        # Statistics frame
        stats_frame = ttk.Frame(right_frame, padding="10")
        stats_frame.pack(fill=tk.X)
        
        self.stats_label = ttk.Label(stats_frame, text="Total Files: 0 | Processed: 0 | Matched: 0")
        self.stats_label.pack(anchor=tk.W)

    def init_file_type_filters(self):
        """Initialize file type filter status (no types selected by default)"""
        pass  # Keep default unselected

    def toggle_category(self, category, init=False):
        """Toggle the selection status of the entire category and synchronize sub-items"""
        target_state = self.category_vars[category].get()
        for ext in FILE_TYPE_CATEGORIES[category]:
            self.extension_vars[ext].set(target_state)
        if not init:
            self.update_included_extensions()

    def update_category_state(self, category):
        """Update category checkbox status based on sub-item status"""
        extensions = FILE_TYPE_CATEGORIES[category]
        checked_count = sum(1 for ext in extensions if self.extension_vars[ext].get())
        
        # Check category if all selected, otherwise uncheck
        self.category_vars[category].set(checked_count == len(extensions))
        self.update_included_extensions()

    def update_included_extensions(self):
        """Update the set of currently selected extensions to include"""
        self.included_extensions = {
            ext for ext, var in self.extension_vars.items() if var.get()
        }

    def add_custom_extension(self):
        """Add a custom extension"""
        ext = simpledialog.askstring("Add Custom Extension", "Please enter the extension (with dot, e.g. .log):")
        if not ext:
            return
            
        # Format extension
        if not ext.startswith('.'):
            ext = '.' + ext
        ext = ext.lower()
        
        # Check if it already exists
        if ext in self.extension_vars:
            messagebox.showinfo("Tip", f"Extension {ext} already exists")
            return
            
        # Add to "Other Files" category (create if not exists)
        if "Other Files" not in FILE_TYPE_CATEGORIES:
            FILE_TYPE_CATEGORIES["Other Files"] = []
            # Create category checkbox
            cat_var = tk.BooleanVar()
            self.category_vars["Other Files"] = cat_var
            cat_check = ttk.Checkbutton(
                self.filter_scrollable_frame,
                text="Other Files", 
                variable=cat_var,
                command=partial(self.toggle_category, "Other Files")
            )
            cat_check.pack(anchor=tk.W, pady=5)
            
            # Create extension sub-frame
            self.other_files_frame = ttk.Frame(self.filter_scrollable_frame)
            self.other_files_frame.pack(anchor=tk.W, padx=20)
        
        # Add to category list
        FILE_TYPE_CATEGORIES["Other Files"].append(ext)
        
        # Create checkbox
        ext_var = tk.BooleanVar()
        self.extension_vars[ext] = ext_var
        ext_check = ttk.Checkbutton(
            self.other_files_frame,
            text=ext, 
            variable=ext_var,
            command=partial(self.update_category_state, "Other Files")
        )
        ext_check.pack(side=tk.LEFT, padx=5, pady=2)
        
        messagebox.showinfo("Success", f"Custom extension {ext} has been added")

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.search_path.set(path)

    def start_search(self):
        if self.is_searching:
            messagebox.showinfo("Tip", "Searching in progress, please stop the current search first")
            return
            
        path = self.search_path.get()
        keyword = self.keyword.get()
        
        if not path:
            messagebox.showerror("Error", "Please select a search path")
            return
            
        if not keyword:
            messagebox.showerror("Error", "Please enter a search keyword")
            return
            
        if not os.path.exists(path):
            messagebox.showerror("Error", "The selected path does not exist")
            return
        
        # Check if file types are selected
        self.update_included_extensions()
        if not self.included_extensions:
            messagebox.showerror("Error", "Please select at least one file type")
            return
            
        # Initialize search status
        self.is_searching = True
        self.stop_event.clear()  # Reset stop event
        self.result_display.delete(1.0, tk.END)
        self.total_files = 0
        self.processed_files = 0
        self.matched_files = 0
        self.update_stats()
        
        # Create queues
        self.progress_queue = self.manager.Queue()
        self.result_queue = self.manager.Queue()
        
        # Start search thread
        self.search_process = threading.Thread(
            target=self.perform_search,
            args=(path, keyword, self.search_type.get())
        )
        self.search_process.daemon = True
        self.search_process.start()
        
        # Start progress and result processing thread
        self.root.after(100, self.process_queue_updates)

    def stop_search(self):
        if self.is_searching and self.search_process:
            self.stop_event.set()
            self.status_label.config(text="Stopping search...")

    def perform_search(self, root_path, keyword, search_type):
        try:
            # Stage 1: Scan all files and filter (keep only selected types)
            self.progress_queue.put(("stage", "Scanning files and filtering (keep only selected types)", 0))
            
            # Get all file list
            all_files = []
            for dirpath, _, filenames in os.walk(root_path):
                if self.stop_event.is_set():
                    self.progress_queue.put(("done", "Search stopped"))
                    return
                    
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    # Check if file extension is in selected types
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in self.included_extensions:  # Core logic change: from exclude to include
                        all_files.append(file_path)
                
                # Update progress
                total_scanned = len(all_files)
                progress = min(100, int((total_scanned / (total_scanned + 1)) * 100))  # Avoid division by zero
                self.progress_queue.put(("stage", "Scanning files and filtering (keep only selected types)", progress))
            
            self.total_files = len(all_files)
            self.progress_queue.put(("total_files", self.total_files))
            self.progress_queue.put(("stage", "File scanning and filtering completed", 100))
            
            if self.total_files == 0:
                self.progress_queue.put(("done", "No files of the selected type found"))
                return
                
            # Stage 2: Search files
            self.progress_queue.put(("stage", f"{'Searching filenames' if search_type == 'name' else 'Searching file contents'}", 0))
            
            # Use multi-processing for search
            num_processes = min(mp.cpu_count(), self.total_files)
            chunk_size = max(1, self.total_files // num_processes)
            
            with Pool(processes=num_processes) as pool:
                # Partially apply function parameters
                if search_type == 'name':
                    search_func = partial(
                        search_filename, 
                        keyword=keyword, 
                        stop_event=self.stop_event,
                        progress_queue=self.progress_queue
                    )
                else:
                    search_func = partial(
                        search_file_content, 
                        keyword=keyword, 
                        stop_event=self.stop_event,
                        progress_queue=self.progress_queue
                    )
                
                # Process file list asynchronously
                results = []
                for i in range(0, self.total_files, chunk_size):
                    chunk = all_files[i:i+chunk_size]
                    results.append(pool.apply_async(search_func, args=(chunk,)))
                
                # Collect results
                for result in results:
                    matched_in_chunk = result.get()
                    for file_path, matches in matched_in_chunk:
                        self.result_queue.put((file_path, matches))
                    
                    if self.stop_event.is_set():
                        pool.terminate()
                        self.progress_queue.put(("done", "Search stopped"))
                        return
            
            self.progress_queue.put(("done", "Search completed"))
            
        except Exception as e:
            self.progress_queue.put(("error", str(e)))

    def process_queue_updates(self):
        if not self.is_searching:
            return
            
        # Process progress updates
        try:
            while not self.progress_queue.empty():
                item = self.progress_queue.get_nowait()
                if item[0] == "stage":
                    stage_name, progress = item[1], item[2]
                    self.stage_label.config(text=stage_name)
                    self.stage_progress["value"] = progress
                elif item[0] == "progress":
                    self.processed_files = item[1]
                    overall_progress = (self.processed_files / self.total_files) * 100 if self.total_files > 0 else 0
                    self.overall_progress["value"] = overall_progress
                    self.status_label.config(text=f"Processing: {item[2]}")
                    self.update_stats()
                elif item[0] == "total_files":
                    self.total_files = item[1]
                    self.update_stats()
                elif item[0] == "done":
                    self.status_label.config(text=item[1])
                    self.is_searching = False
                elif item[0] == "error":
                    messagebox.showerror("Error", f"An error occurred during search: {item[1]}")
                    self.is_searching = False
        
        except queue.Empty:
            pass
        
        # Process result updates
        try:
            while not self.result_queue.empty():
                item = self.result_queue.get_nowait()
                file_path, matches = item
                self.matched_files += 1
                self.display_result(file_path, matches)
                self.update_stats()
        except queue.Empty:
            pass
        
        # Continue checking queue or finish
        if self.is_searching:
            self.root.after(100, self.process_queue_updates)
        else:
            self.overall_progress["value"] = 100
            self.stage_progress["value"] = 100

    def display_result(self, file_path, matches):
        # Insert separator
        self.result_display.insert(tk.END, "----------------------------\n", "separator")
        
        # Display file name (blue bold)
        self.result_display.insert(tk.END, f"File Path: {file_path}\n", "filename")
        
        # If there are matching contents, display line numbers and matching snippets
        if matches and self.search_type.get() == "content":
            self.result_display.insert(tk.END, "  Matching Contents:\n")
            for line_num, line_content in matches[:5]:  # Show only first 5 matches
                # Display line number (green)
                self.result_display.insert(tk.END, f"    Line {line_num}: ", "linenum")
                start_pos = self.result_display.index(tk.END)
                self.result_display.insert(tk.END, line_content + "\n")
                end_pos = self.result_display.index(tk.END)
                
                # Mark matched keywords (yellow highlight)
                start = start_pos
                keyword = self.keyword.get()
                while True:
                    start = self.result_display.search(keyword, start, end_pos, nocase=True)
                    if not start:
                        break
                    line, col = map(int, start.split('.'))
                    end = f"{line}.{col + len(keyword)}"
                    self.result_display.tag_add("match", start, end)
                    start = end
        
        self.result_display.see(tk.END)

    def update_stats(self):
        self.stats_label.config(
            text=f"Total Files: {self.total_files} | Processed: {self.processed_files} | Matched: {self.matched_files}"
        )

# Multi-process helper function - Search filenames
def search_filename(files, keyword, stop_event, progress_queue):
    matched = []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    
    for i, file_path in enumerate(files):
        if stop_event.is_set():
            return []
            
        filename = os.path.basename(file_path)
        if pattern.search(filename):
            matched.append((file_path, []))
            
        # Update progress
        if i % 10 == 0 or i == len(files) - 1:
            progress_queue.put(("progress", i + 1, file_path))
    
    return matched

# Multi-process helper function - Search file contents
def search_file_content(files, keyword, stop_event, progress_queue):
    matched = []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    
    for i, file_path in enumerate(files):
        if stop_event.is_set():
            return []
            
        try:
            # Try to determine file type, skip binary files
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type and mime_type.startswith(('image/', 'audio/', 'video/')):
                continue
                
            # Try to open file as text
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                matches_in_file = []
                for line_num, line in enumerate(f, 1):
                    if pattern.search(line):
                        # Extract context of matched line
                        start = max(0, line.find(keyword) - 30)
                        end = min(len(line), line.find(keyword) + len(keyword) + 30)
                        snippet = line[start:end].replace('\n', ' ').replace('\r', '')
                        matches_in_file.append((line_num, snippet))
                        
                        # Limit to max 10 matches per file
                        if len(matches_in_file) >= 10:
                            break
                
                if matches_in_file:
                    matched.append((file_path, matches_in_file))
                    
        except (IOError, UnicodeDecodeError):
            # Skip unreadable files
            pass
            
        # Update progress
        if i % 10 == 0 or i == len(files) - 1:
            progress_queue.put(("progress", i + 1, file_path))
    
    return matched

if __name__ == "__main__":
    # Need to protect main module when running multi-process on Windows
    if os.name == 'nt':
        mp.set_start_method('spawn')
    
    root = tk.Tk()
    app = FileSearchApp(root)
    root.mainloop()