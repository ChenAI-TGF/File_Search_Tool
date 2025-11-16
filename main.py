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

# 定义文件类型分类（可扩展）
FILE_TYPE_CATEGORIES = {
    "音频文件": ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.ape', '.alac'],
    "视频文件": ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.mpg', '.mpeg', '.rmvb', '.3gp'],
    "图像文件": ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg', '.psd', '.ai'],
    "文档文件": ['.doc', '.docx', '.pdf', '.txt', '.xls', '.xlsx', '.ppt', '.pptx', '.md', '.rtf'],
    "压缩文件": ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
    "程序文件": ['.exe', '.dll', '.py', '.java', '.c', '.cpp', '.js', '.html', '.css']
}

class FileSearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文件智能搜索工具")
        self.root.geometry("1200x700")
        self.root.minsize(1000, 600)
        
        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure(".", font=("SimHei", 10))
        
        # 搜索参数
        self.search_path = tk.StringVar()
        self.keyword = tk.StringVar()
        self.search_type = tk.StringVar(value="name")  # name 或 content
        self.is_searching = False
        self.manager = Manager()  # 用于创建跨进程共享对象
        self.stop_event = self.manager.Event()  # 改用Manager创建Event
        
        # 文件类型筛选状态（改为：只搜索选中的类型）
        self.category_vars = {}  # 存储类别勾选状态
        self.extension_vars = {}  # 存储扩展名勾选状态
        self.included_extensions = set()  # 当前选中的要包含的扩展名
        self.other_files_frame = None  # 存储"其他文件"类别的扩展架子框架
        
        # 创建UI
        self.create_widgets()
        # 初始化文件类型筛选状态（默认不选中任何类型）
        self.init_file_type_filters()
        
        # 进程和队列
        self.progress_queue = None
        self.result_queue = None
        self.search_process = None
        
        # 搜索统计
        self.total_files = 0
        self.processed_files = 0
        self.matched_files = 0

    def create_widgets(self):
        # 主框架分割为左右两部分
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：文件类型筛选面板（功能改为只搜索选中类型）
        filter_frame = ttk.LabelFrame(main_paned, text="文件类型筛选（只搜索选中类型）", padding="10")
        main_paned.add(filter_frame, weight=1)
        
        # 筛选面板滚动区域 - 定义为类属性
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
        
        # 添加文件类型分类和扩展名复选框
        for category, extensions in FILE_TYPE_CATEGORIES.items():
            # 类别总复选框
            cat_var = tk.BooleanVar()
            self.category_vars[category] = cat_var
            cat_check = ttk.Checkbutton(
                self.filter_scrollable_frame, 
                text=category, 
                variable=cat_var,
                command=partial(self.toggle_category, category)
            )
            cat_check.pack(anchor=tk.W, pady=5)
            
            # 该类别下的扩展名复选框
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
        
        # 添加自定义扩展名按钮
        ttk.Button(
            filter_frame, 
            text="添加自定义扩展名", 
            command=self.add_custom_extension
        ).pack(pady=10, fill=tk.X)
        
        # 右侧：主功能区
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=3)
        
        # 顶部框架 - 路径选择
        path_frame = ttk.Frame(right_frame, padding="10")
        path_frame.pack(fill=tk.X)
        
        ttk.Label(path_frame, text="搜索路径:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(path_frame, textvariable=self.search_path, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(path_frame, text="浏览...", command=self.browse_path).pack(side=tk.LEFT, padx=5)
        
        # 中间框架 - 搜索设置
        search_frame = ttk.Frame(right_frame, padding="10")
        search_frame.pack(fill=tk.X)
        
        ttk.Label(search_frame, text="搜索关键词:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(search_frame, textvariable=self.keyword, width=30).pack(side=tk.LEFT, padx=5)
        
        ttk.Radiobutton(search_frame, text="按文件名", variable=self.search_type, value="name").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(search_frame, text="按文件内容", variable=self.search_type, value="content").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(search_frame, text="开始搜索", command=self.start_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(search_frame, text="停止搜索", command=self.stop_search).pack(side=tk.LEFT, padx=5)
        
        # 进度框架
        progress_frame = ttk.Frame(right_frame, padding="10")
        progress_frame.pack(fill=tk.X)
        
        ttk.Label(progress_frame, text="总体进度:").pack(side=tk.LEFT, padx=5)
        self.overall_progress = ttk.Progressbar(progress_frame, orient="horizontal", length=100, mode="determinate")
        self.overall_progress.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # 阶段进度框架
        stage_frame = ttk.Frame(right_frame, padding="10")
        stage_frame.pack(fill=tk.X)
        
        ttk.Label(stage_frame, text="当前阶段:").pack(side=tk.LEFT, padx=5)
        self.stage_label = ttk.Label(stage_frame, text="准备就绪")
        self.stage_label.pack(side=tk.LEFT, padx=5)
        
        self.stage_progress = ttk.Progressbar(stage_frame, orient="horizontal", length=100, mode="determinate")
        self.stage_progress.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # 状态框架
        status_frame = ttk.Frame(right_frame, padding="10")
        status_frame.pack(fill=tk.X)
        
        self.status_label = ttk.Label(status_frame, text="等待开始搜索...")
        self.status_label.pack(anchor=tk.W)
        
        # 结果框架
        result_frame = ttk.LabelFrame(right_frame, text="搜索结果", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        self.result_display = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD)
        self.result_display.pack(fill=tk.BOTH, expand=True, pady=5)
        # 配置不同内容的样式标签
        self.result_display.tag_configure("filename", foreground="blue", font=("SimHei", 10, "bold"))
        self.result_display.tag_configure("linenum", foreground="green", font=("SimHei", 10))
        self.result_display.tag_configure("match", background="yellow")
        self.result_display.tag_configure("separator", foreground="gray")
        
        # 统计信息框架
        stats_frame = ttk.Frame(right_frame, padding="10")
        stats_frame.pack(fill=tk.X)
        
        self.stats_label = ttk.Label(stats_frame, text="文件总数: 0 | 已处理: 0 | 匹配: 0")
        self.stats_label.pack(anchor=tk.W)

    def init_file_type_filters(self):
        """初始化文件类型筛选状态（默认不选中任何类型）"""
        pass  # 保持默认不选中

    def toggle_category(self, category, init=False):
        """切换整个类别的选中状态，同步子项"""
        target_state = self.category_vars[category].get()
        for ext in FILE_TYPE_CATEGORIES[category]:
            self.extension_vars[ext].set(target_state)
        if not init:
            self.update_included_extensions()

    def update_category_state(self, category):
        """根据子项状态更新类别复选框状态"""
        extensions = FILE_TYPE_CATEGORIES[category]
        checked_count = sum(1 for ext in extensions if self.extension_vars[ext].get())
        
        # 全选则勾选类别，否则不勾选
        self.category_vars[category].set(checked_count == len(extensions))
        self.update_included_extensions()

    def update_included_extensions(self):
        """更新当前选中的要包含的扩展名集合"""
        self.included_extensions = {
            ext for ext, var in self.extension_vars.items() if var.get()
        }

    def add_custom_extension(self):
        """添加自定义扩展名"""
        ext = simpledialog.askstring("添加自定义扩展名", "请输入扩展名（带点，如 .log）:")
        if not ext:
            return
            
        # 格式化扩展名
        if not ext.startswith('.'):
            ext = '.' + ext
        ext = ext.lower()
        
        # 检查是否已存在
        if ext in self.extension_vars:
            messagebox.showinfo("提示", f"扩展名 {ext} 已存在")
            return
            
        # 添加到"其他文件"类别（如果不存在则创建）
        if "其他文件" not in FILE_TYPE_CATEGORIES:
            FILE_TYPE_CATEGORIES["其他文件"] = []
            # 创建类别复选框
            cat_var = tk.BooleanVar()
            self.category_vars["其他文件"] = cat_var
            cat_check = ttk.Checkbutton(
                self.filter_scrollable_frame,
                text="其他文件", 
                variable=cat_var,
                command=partial(self.toggle_category, "其他文件")
            )
            cat_check.pack(anchor=tk.W, pady=5)
            
            # 创建扩展架子框架
            self.other_files_frame = ttk.Frame(self.filter_scrollable_frame)
            self.other_files_frame.pack(anchor=tk.W, padx=20)
        
        # 添加到类别列表
        FILE_TYPE_CATEGORIES["其他文件"].append(ext)
        
        # 创建复选框
        ext_var = tk.BooleanVar()
        self.extension_vars[ext] = ext_var
        ext_check = ttk.Checkbutton(
            self.other_files_frame,
            text=ext, 
            variable=ext_var,
            command=partial(self.update_category_state, "其他文件")
        )
        ext_check.pack(side=tk.LEFT, padx=5, pady=2)
        
        messagebox.showinfo("成功", f"已添加自定义扩展名 {ext}")

    def browse_path(self):
        path = filedialog.askdirectory()
        if path:
            self.search_path.set(path)

    def start_search(self):
        if self.is_searching:
            messagebox.showinfo("提示", "正在搜索中，请先停止当前搜索")
            return
            
        path = self.search_path.get()
        keyword = self.keyword.get()
        
        if not path:
            messagebox.showerror("错误", "请选择搜索路径")
            return
            
        if not keyword:
            messagebox.showerror("错误", "请输入搜索关键词")
            return
            
        if not os.path.exists(path):
            messagebox.showerror("错误", "所选路径不存在")
            return
        
        # 检查是否选择了文件类型
        self.update_included_extensions()
        if not self.included_extensions:
            messagebox.showerror("错误", "请至少选择一种文件类型")
            return
            
        # 初始化搜索状态
        self.is_searching = True
        self.stop_event.clear()  # 重置停止事件
        self.result_display.delete(1.0, tk.END)
        self.total_files = 0
        self.processed_files = 0
        self.matched_files = 0
        self.update_stats()
        
        # 创建队列
        self.progress_queue = self.manager.Queue()
        self.result_queue = self.manager.Queue()
        
        # 启动搜索进程
        self.search_process = threading.Thread(
            target=self.perform_search,
            args=(path, keyword, self.search_type.get())
        )
        self.search_process.daemon = True
        self.search_process.start()
        
        # 启动进度和结果处理线程
        self.root.after(100, self.process_queue_updates)

    def stop_search(self):
        if self.is_searching and self.search_process:
            self.stop_event.set()
            self.status_label.config(text="正在停止搜索...")

    def perform_search(self, root_path, keyword, search_type):
        try:
            # 阶段1: 扫描所有文件并过滤（只保留选中类型）
            self.progress_queue.put(("stage", "扫描文件并过滤（只保留选中类型）", 0))
            
            # 获取所有文件列表
            all_files = []
            for dirpath, _, filenames in os.walk(root_path):
                if self.stop_event.is_set():
                    self.progress_queue.put(("done", "搜索已停止"))
                    return
                    
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    # 检查文件扩展名是否在选中的类型中
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in self.included_extensions:  # 核心逻辑变更：从排除变为包含
                        all_files.append(file_path)
                
                # 更新进度
                total_scanned = len(all_files)
                progress = min(100, int((total_scanned / (total_scanned + 1)) * 100))  # 避免除以0
                self.progress_queue.put(("stage", "扫描文件并过滤（只保留选中类型）", progress))
            
            self.total_files = len(all_files)
            self.progress_queue.put(("total_files", self.total_files))
            self.progress_queue.put(("stage", "扫描文件并过滤完成", 100))
            
            if self.total_files == 0:
                self.progress_queue.put(("done", "未找到符合条件的文件类型"))
                return
                
            # 阶段2: 搜索文件
            self.progress_queue.put(("stage", f"正在{('搜索文件名' if search_type == 'name' else '搜索文件内容')}", 0))
            
            # 使用多进程搜索
            num_processes = min(mp.cpu_count(), self.total_files)
            chunk_size = max(1, self.total_files // num_processes)
            
            with Pool(processes=num_processes) as pool:
                # 部分应用函数参数
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
                
                # 异步处理文件列表
                results = []
                for i in range(0, self.total_files, chunk_size):
                    chunk = all_files[i:i+chunk_size]
                    results.append(pool.apply_async(search_func, args=(chunk,)))
                
                # 收集结果
                for result in results:
                    matched_in_chunk = result.get()
                    for file_path, matches in matched_in_chunk:
                        self.result_queue.put((file_path, matches))
                    
                    if self.stop_event.is_set():
                        pool.terminate()
                        self.progress_queue.put(("done", "搜索已停止"))
                        return
            
            self.progress_queue.put(("done", "搜索完成"))
            
        except Exception as e:
            self.progress_queue.put(("error", str(e)))

    def process_queue_updates(self):
        if not self.is_searching:
            return
            
        # 处理进度更新
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
                    self.status_label.config(text=f"正在处理: {item[2]}")
                    self.update_stats()
                elif item[0] == "total_files":
                    self.total_files = item[1]
                    self.update_stats()
                elif item[0] == "done":
                    self.status_label.config(text=item[1])
                    self.is_searching = False
                elif item[0] == "error":
                    messagebox.showerror("错误", f"搜索过程中发生错误: {item[1]}")
                    self.is_searching = False
        
        except queue.Empty:
            pass
        
        # 处理结果更新
        try:
            while not self.result_queue.empty():
                item = self.result_queue.get_nowait()
                file_path, matches = item
                self.matched_files += 1
                self.display_result(file_path, matches)
                self.update_stats()
        except queue.Empty:
            pass
        
        # 继续检查队列或结束
        if self.is_searching:
            self.root.after(100, self.process_queue_updates)
        else:
            self.overall_progress["value"] = 100
            self.stage_progress["value"] = 100

    def display_result(self, file_path, matches):
        # 插入分割线
        self.result_display.insert(tk.END, "----------------------------\n", "separator")
        
        # 显示文件名（蓝色加粗）
        self.result_display.insert(tk.END, f"文件路径: {file_path}\n", "filename")
        
        # 如果有匹配内容，显示行数和匹配片段
        if matches and self.search_type.get() == "content":
            self.result_display.insert(tk.END, "  匹配内容:\n")
            for line_num, line_content in matches[:5]:  # 只显示前5个匹配
                # 显示行数（绿色）
                self.result_display.insert(tk.END, f"    第{line_num}行: ", "linenum")
                start_pos = self.result_display.index(tk.END)
                self.result_display.insert(tk.END, line_content + "\n")
                end_pos = self.result_display.index(tk.END)
                
                # 标记匹配的关键词（黄色高亮）
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
            text=f"文件总数: {self.total_files} | 已处理: {self.processed_files} | 匹配: {self.matched_files}"
        )

# 多进程辅助函数 - 搜索文件名
def search_filename(files, keyword, stop_event, progress_queue):
    matched = []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    
    for i, file_path in enumerate(files):
        if stop_event.is_set():
            return []
            
        filename = os.path.basename(file_path)
        if pattern.search(filename):
            matched.append((file_path, []))
            
        # 更新进度
        if i % 10 == 0 or i == len(files) - 1:
            progress_queue.put(("progress", i + 1, file_path))
    
    return matched

# 多进程辅助函数 - 搜索文件内容
def search_file_content(files, keyword, stop_event, progress_queue):
    matched = []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    
    for i, file_path in enumerate(files):
        if stop_event.is_set():
            return []
            
        try:
            # 尝试确定文件类型，跳过二进制文件
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type and mime_type.startswith(('image/', 'audio/', 'video/')):
                continue
                
            # 尝试以文本方式打开文件
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                matches_in_file = []
                for line_num, line in enumerate(f, 1):
                    if pattern.search(line):
                        # 截取匹配行的上下文
                        start = max(0, line.find(keyword) - 30)
                        end = min(len(line), line.find(keyword) + len(keyword) + 30)
                        snippet = line[start:end].replace('\n', ' ').replace('\r', '')
                        matches_in_file.append((line_num, snippet))
                        
                        # 限制每个文件最多记录10个匹配
                        if len(matches_in_file) >= 10:
                            break
                
                if matches_in_file:
                    matched.append((file_path, matches_in_file))
                    
        except (IOError, UnicodeDecodeError):
            # 无法读取的文件跳过
            pass
            
        # 更新进度
        if i % 10 == 0 or i == len(files) - 1:
            progress_queue.put(("progress", i + 1, file_path))
    
    return matched

if __name__ == "__main__":
    # 在Windows上运行多进程需要保护主模块
    if os.name == 'nt':
        mp.set_start_method('spawn')
    
    root = tk.Tk()
    app = FileSearchApp(root)
    root.mainloop()