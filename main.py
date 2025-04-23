import os
import sys
import time
import requests
import json
import pandas as pd
import base64
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import configparser
import logging
from datetime import datetime

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Hỗ trợ bundling resource vào file exe
def resource_path(relative_path):
    """ Lấy đường dẫn tuyệt đối đến resource """
    try:
        # PyInstaller tạo thư mục temp
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Đảm bảo có thư mục dữ liệu khi chạy
def ensure_app_dirs():
    app_data_dir = os.path.join(os.path.expanduser("~"), "MiniMaxVideoGenerator")
    os.makedirs(app_data_dir, exist_ok=True)
    return app_data_dir

class ConfigManager:
    def __init__(self):
        self.app_data_dir = ensure_app_dirs()
        self.config = configparser.ConfigParser()
        self.config_file = os.path.join(self.app_data_dir, 'config.ini')
        
        # Thiết lập mặc định
        self.api_key = ""
        self.output_folder = os.path.join(os.path.expanduser("~"), "MiniMaxVideos")
        self.max_videos_per_image = 1
        self.model = "I2V-01-Director"
        self.max_concurrent_tasks = 3
        
        # Đọc cấu hình hoặc tạo mới
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
            self.load_config()
        else:
            self.create_default_config()
    
    def load_config(self):
        """Tải cấu hình từ file"""
        if 'API' in self.config:
            self.api_key = self.config['API'].get('key', "")
        if 'Settings' in self.config:
            self.output_folder = self.config['Settings'].get('output_folder', os.path.join(os.path.expanduser("~"), "MiniMaxVideos"))
            self.max_videos_per_image = int(self.config['Settings'].get('max_videos_per_image', 1))
            self.model = self.config['Settings'].get('model', "I2V-01-Director")
            self.max_concurrent_tasks = int(self.config['Settings'].get('max_concurrent_tasks', 3))
    
    def create_default_config(self):
        """Tạo cấu hình mặc định"""
        self.config['API'] = {'key': ""}
        self.config['Settings'] = {
            'output_folder': self.output_folder,
            'max_videos_per_image': str(self.max_videos_per_image),
            'model': self.model,
            'max_concurrent_tasks': str(self.max_concurrent_tasks)
        }
        self.save_config()
    
    def save_config(self):
        """Lưu cấu hình hiện tại vào file"""
        self.config['API'] = {'key': self.api_key}
        self.config['Settings'] = {
            'output_folder': self.output_folder,
            'max_videos_per_image': str(self.max_videos_per_image),
            'model': self.model,
            'max_concurrent_tasks': str(self.max_concurrent_tasks)
        }
        
        with open(self.config_file, 'w') as f:
            self.config.write(f)


class MiniMaxAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.minimaxi.chat/v1"
        self.headers = {
            'authorization': f'Bearer {self.api_key}',
            'content-type': 'application/json'
        }
    
    def encode_image(self, image_path):
        """Mã hóa image thành base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def create_video_task(self, image_path, prompt, model="I2V-01-Director"):
        """Tạo task tạo video từ hình ảnh và prompt"""
        encoded_image = self.encode_image(image_path)
        
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "first_frame_image": encoded_image
        })
        
        url = f"{self.base_url}/video_generation"
        response = requests.post(url, headers=self.headers, data=payload)
        
        if response.status_code != 200:
            raise Exception(f"Lỗi khi tạo task: {response.text}")
        
        return response.json()
    
    def query_task_status(self, task_id):
        """Truy vấn trạng thái của task tạo video"""
        url = f"{self.base_url}/query/video_generation?task_id={task_id}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            raise Exception(f"Lỗi khi truy vấn task: {response.text}")
        
        return response.json()
    
    def retrieve_video(self, file_id):
        """Lấy URL tải video đã tạo"""
        url = f"{self.base_url}/files/retrieve?file_id={file_id}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            raise Exception(f"Lỗi khi truy xuất file: {response.text}")
        
        return response.json()
    
    def download_video(self, download_url, output_path):
        """Tải video từ URL đã cung cấp"""
        response = requests.get(download_url)
        
        if response.status_code != 200:
            raise Exception(f"Lỗi khi tải file: {response.status_code}")
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path


class ExcelProcessor:
    def __init__(self):
        self.data = None
        self.excel_path = None
    
    def load_excel(self, excel_path):
        """Tải dữ liệu prompt từ file Excel"""
        try:
            self.data = pd.read_excel(excel_path)
            self.excel_path = excel_path
            return True
        except Exception as e:
            logging.error(f"Lỗi khi tải file Excel: {e}")
            return False
    
    def get_prompt_for_image(self, image_name):
        """Tìm prompt cho tên file ảnh cụ thể"""
        if self.data is None:
            return None
        
        # Tìm dựa trên tên file ảnh
        image_basename = os.path.basename(image_name)
        
        # Kiểm tra nếu cột 'image' tồn tại và chứa tên ảnh
        if 'image' in self.data.columns:
            matches = self.data[self.data['image'] == image_basename]
            if not matches.empty and 'prompt' in matches.columns:
                return matches.iloc[0]['prompt']
        
        # Nếu không tìm thấy, trả về None
        return None
    
    def update_prompt_for_image(self, image_path, new_prompt):
        """Cập nhật prompt cho một ảnh cụ thể trong Excel"""
        if self.data is None:
            return False
        
        image_basename = os.path.basename(image_path)
        
        # Tìm dòng chứa tên ảnh
        if 'image' in self.data.columns:
            mask = self.data['image'] == image_basename
            if mask.any():
                # Nếu có cột prompt, cập nhật giá trị
                if 'prompt' in self.data.columns:
                    self.data.loc[mask, 'prompt'] = new_prompt
                else:
                    # Nếu không có cột prompt, thêm cột mới
                    self.data['prompt'] = ""
                    self.data.loc[mask, 'prompt'] = new_prompt
                return True
        
        # Nếu không tìm thấy ảnh, thêm dòng mới
        if 'image' in self.data.columns and 'prompt' in self.data.columns:
            new_row = pd.DataFrame({'image': [image_basename], 'prompt': [new_prompt]})
            self.data = pd.concat([self.data, new_row], ignore_index=True)
            return True
        
        return False
    
    def save_excel(self, excel_path=None):
        """Lưu dữ liệu vào file Excel"""
        if self.data is None:
            return False
        
        if excel_path is None:
            if not hasattr(self, 'excel_path') or not self.excel_path:
                return False
            excel_path = self.excel_path
        
        try:
            self.data.to_excel(excel_path, index=False)
            return True
        except Exception as e:
            logging.error(f"Lỗi khi lưu file Excel: {e}")
            return False


class TaskQueueManager:
    def __init__(self, api_client, max_concurrent_tasks=3, poll_interval=10):
        self.api_client = api_client
        self.max_concurrent_tasks = max_concurrent_tasks
        self.poll_interval = poll_interval  # Giây
        
        self.task_queue = queue.Queue()
        self.active_tasks = {}  # task_id -> task_info
        self.completed_tasks = []
        self.failed_tasks = []
        
        self.running = False
        self.queue_thread = None
        self.lock = threading.Lock()
        
        # Callbacks
        self.on_task_completed = None
        self.on_task_failed = None
        self.on_task_started = None
        self.on_queue_updated = None
    
    def add_task(self, image_path, prompt, output_filename, model="I2V-01-Director"):
        """Thêm task mới vào hàng đợi"""
        task_info = {
            'image_path': image_path,
            'prompt': prompt,
            'output_filename': output_filename,
            'model': model,
            'status': 'queued',
            'added_time': datetime.now(),
            'task_id': None,
            'file_id': None
        }
        
        self.task_queue.put(task_info)
        
        if self.on_queue_updated:
            self.on_queue_updated()
            
        if not self.running:
            self.start_processing()
    
    def start_processing(self):
        """Bắt đầu xử lý hàng đợi task"""
        if self.running:
            return
        
        self.running = True
        self.queue_thread = threading.Thread(target=self._process_queue)
        self.queue_thread.daemon = True
        self.queue_thread.start()
    
    def stop_processing(self):
        """Dừng xử lý hàng đợi task"""
        self.running = False
        if self.queue_thread and self.queue_thread.is_alive():
            self.queue_thread.join(timeout=2.0)
    
    def _process_queue(self):
        """Vòng lặp xử lý hàng đợi chính"""
        while self.running:
            # Bắt đầu task mới nếu còn dung lượng
            while len(self.active_tasks) < self.max_concurrent_tasks and not self.task_queue.empty():
                task_info = self.task_queue.get()
                try:
                    response = self.api_client.create_video_task(
                        task_info['image_path'],
                        task_info['prompt'],
                        task_info['model']
                    )
                    
                    task_id = response.get('task_id')
                    if not task_id:
                        raise Exception(f"Không nhận được task_id: {response}")
                    
                    task_info['task_id'] = task_id
                    task_info['status'] = 'processing'
                    task_info['start_time'] = datetime.now()
                    
                    with self.lock:
                        self.active_tasks[task_id] = task_info
                    
                    if self.on_task_started:
                        self.on_task_started(task_info)
                    
                except Exception as e:
                    task_info['status'] = 'failed'
                    task_info['error'] = str(e)
                    self.failed_tasks.append(task_info)
                    
                    if self.on_task_failed:
                        self.on_task_failed(task_info)
                
                finally:
                    self.task_queue.task_done()
                    if self.on_queue_updated:
                        self.on_queue_updated()
            
            # Kiểm tra trạng thái của các task đang hoạt động
            completed_tasks = []
            for task_id, task_info in list(self.active_tasks.items()):
                try:
                    status_resp = self.api_client.query_task_status(task_id)
                    current_status = status_resp.get('status')
                    
                    if current_status == 'Success':
                        file_id = status_resp.get('file_id')
                        if not file_id:
                            raise Exception(f"Không nhận được file_id cho task đã hoàn thành: {status_resp}")
                        
                        task_info['file_id'] = file_id
                        task_info['status'] = 'downloading'
                        
                        # Truy xuất URL tải xuống
                        file_resp = self.api_client.retrieve_video(file_id)
                        download_url = file_resp.get('file', {}).get('download_url')
                        
                        if not download_url:
                            raise Exception(f"Không nhận được download_url: {file_resp}")
                        
                        # Tải video
                        output_path = task_info['output_filename']
                        self.api_client.download_video(download_url, output_path)
                        
                        task_info['status'] = 'completed'
                        task_info['completion_time'] = datetime.now()
                        
                        completed_tasks.append(task_id)
                        self.completed_tasks.append(task_info)
                        
                        if self.on_task_completed:
                            self.on_task_completed(task_info)
                    
                    elif current_status == 'Fail':
                        task_info['status'] = 'failed'
                        task_info['error'] = f"Task thất bại: {status_resp}"
                        
                        completed_tasks.append(task_id)
                        self.failed_tasks.append(task_info)
                        
                        if self.on_task_failed:
                            self.on_task_failed(task_info)
                    
                    # Các trạng thái khác vẫn đang xử lý
                    
                except Exception as e:
                    task_info['status'] = 'failed'
                    task_info['error'] = str(e)
                    
                    completed_tasks.append(task_id)
                    self.failed_tasks.append(task_info)
                    
                    if self.on_task_failed:
                        self.on_task_failed(task_info)
            
            # Xóa các task đã hoàn thành khỏi danh sách task đang hoạt động
            with self.lock:
                for task_id in completed_tasks:
                    if task_id in self.active_tasks:
                        del self.active_tasks[task_id]
            
            if self.on_queue_updated:
                self.on_queue_updated()
            
            # Ngủ trước khi kiểm tra tiếp
            time.sleep(self.poll_interval)


class TaskStatisticsManager:
    def __init__(self, task_queue_manager):
        self.task_queue_manager = task_queue_manager
        self.processing_times = []  # Danh sách thời gian xử lý của các task đã hoàn thành
        self.last_update_time = datetime.now()
        
    def update_stats(self):
        """Cập nhật thống kê dựa trên dữ liệu hiện tại"""
        stats = {
            'total_tasks': (len(self.task_queue_manager.task_queue.queue) + 
                          len(self.task_queue_manager.active_tasks) + 
                          len(self.task_queue_manager.completed_tasks) + 
                          len(self.task_queue_manager.failed_tasks)),
            'queued_tasks': len(self.task_queue_manager.task_queue.queue),
            'active_tasks': len(self.task_queue_manager.active_tasks),
            'completed_tasks': len(self.task_queue_manager.completed_tasks),
            'failed_tasks': len(self.task_queue_manager.failed_tasks),
            'success_rate': self._calculate_success_rate(),
            'avg_processing_time': self._calculate_avg_processing_time(),
            'estimated_completion_time': self._estimate_completion_time()
        }
        return stats
    
    def _calculate_success_rate(self):
        """Tính tỷ lệ thành công"""
        total_completed = len(self.task_queue_manager.completed_tasks) + len(self.task_queue_manager.failed_tasks)
        if total_completed == 0:
            return 0
        return (len(self.task_queue_manager.completed_tasks) / total_completed) * 100
    
    def _calculate_avg_processing_time(self):
        """Tính thời gian xử lý trung bình (giây)"""
        if not self.processing_times:
            # Tính từ các task đã hoàn thành
            for task in self.task_queue_manager.completed_tasks:
                if 'start_time' in task and 'completion_time' in task:
                    time_diff = (task['completion_time'] - task['start_time']).total_seconds()
                    self.processing_times.append(time_diff)
        
        if not self.processing_times:
            return None
            
        return sum(self.processing_times) / len(self.processing_times)
    
    def _estimate_completion_time(self):
        """Ước tính thời gian hoàn thành tất cả task (giây)"""
        avg_time = self._calculate_avg_processing_time()
        if avg_time is None:
            return None
            
        remaining_tasks = len(self.task_queue_manager.task_queue.queue)
        active_tasks = len(self.task_queue_manager.active_tasks)
        
        if remaining_tasks == 0 and active_tasks == 0:
            return 0
            
        concurrent_tasks = max(1, self.task_queue_manager.max_concurrent_tasks)
        
        # Thời gian để hoàn thành các task đang chạy (lấy task lâu nhất)
        active_time = 0
        for task_id, task in self.task_queue_manager.active_tasks.items():
            if 'start_time' in task:
                elapsed = (datetime.now() - task['start_time']).total_seconds()
                remaining = max(0, avg_time - elapsed)
                active_time = max(active_time, remaining)
        
        # Thời gian để xử lý các task còn lại trong hàng đợi
        queue_time = (remaining_tasks / concurrent_tasks) * avg_time
        
        return active_time + queue_time


class PromptLibrary:
    def __init__(self):
        self.app_data_dir = ensure_app_dirs()
        self.library_file = os.path.join(self.app_data_dir, 'prompt_library.json')
        self.categories = []
        self.prompts = {}
        self.load_library()
    
    def load_library(self):
        """Tải thư viện prompt từ file"""
        if os.path.exists(self.library_file):
            try:
                with open(self.library_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.categories = data.get('categories', [])
                    self.prompts = data.get('prompts', {})
            except Exception as e:
                logging.error(f"Lỗi khi tải thư viện prompt: {e}")
                self._create_default_library()
        else:
            self._create_default_library()
    
    def _create_default_library(self):
        """Tạo thư viện mặc định nếu không tìm thấy file"""
        self.categories = ["Phong cảnh", "Chân dung", "Sản phẩm", "Động vật", "Chuyển động camera"]
        
        self.prompts = {
            "Phong cảnh": [
                {"name": "Hoàng hôn biển", "prompt": "Cảnh hoàng hôn đẹp trên bờ biển với sóng vỗ nhẹ nhàng."},
                {"name": "Núi tuyết", "prompt": "Dãy núi cao phủ tuyết trắng, mây mù bao phủ đỉnh núi."}
            ],
            "Chân dung": [
                {"name": "Chân dung nghệ thuật", "prompt": "Chân dung nghệ thuật với ánh sáng tự nhiên, nền mờ."},
                {"name": "Chân dung phong cách", "prompt": "Chân dung phong cách thời trang với tông màu trung tính."}
            ],
            "Chuyển động camera": [
                {"name": "Zoom vào chủ thể", "prompt": "[Zoom in] Cận cảnh chi tiết của chủ thể."},
                {"name": "Pan cảnh", "prompt": "[Pan left] Quét qua cảnh từ phải sang trái, hiển thị toàn cảnh."},
                {"name": "Truck và Zoom", "prompt": "[Truck right, Zoom in] Di chuyển sang phải đồng thời zoom vào chủ thể."}
            ]
        }
        
        self.save_library()
    
    def save_library(self):
        """Lưu thư viện prompt vào file"""
        data = {
            'categories': self.categories,
            'prompts': self.prompts
        }
        
        try:
            with open(self.library_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Lỗi khi lưu thư viện prompt: {e}")
    
    def add_prompt(self, category, name, prompt_text):
        """Thêm prompt mới vào thư viện"""
        if category not in self.categories:
            self.categories.append(category)
            self.prompts[category] = []
        
        # Kiểm tra xem prompt đã tồn tại chưa
        for i, prompt in enumerate(self.prompts[category]):
            if prompt["name"] == name:
                # Cập nhật prompt hiện có
                self.prompts[category][i] = {"name": name, "prompt": prompt_text}
                self.save_library()
                return
        
        # Thêm prompt mới
        self.prompts[category].append({"name": name, "prompt": prompt_text})
        self.save_library()
    
    def get_prompts_by_category(self, category):
        """Lấy danh sách prompt theo category"""
        if category in self.prompts:
            return self.prompts[category]
        return []


class PromptEditorWindow:
    def __init__(self, parent, prompt_library, initial_prompt="", callback=None):
        self.top = tk.Toplevel(parent)
        self.top.title("Soạn thảo Prompt nâng cao")
        self.top.geometry("800x600")
        self.top.minsize(700, 500)
        
        self.prompt_library = prompt_library
        self.initial_prompt = initial_prompt
        self.callback = callback
        
        self.camera_moves = [
            "Truck left", "Truck right",
            "Pan left", "Pan right",
            "Push in", "Pull out",
            "Pedestal up", "Pedestal down",
            "Tilt up", "Tilt down",
            "Zoom in", "Zoom out",
            "Shake", "Tracking shot", "Static shot"
        ]
        
        self.create_widgets()
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.top, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        # Panel trên cùng - Camera Movements
        camera_frame = ttk.LabelFrame(main_frame, text="Chuyển động Camera")
        camera_frame.pack(fill="x", expand=False, pady=(0, 10))
        
        camera_buttons_frame = ttk.Frame(camera_frame)
        camera_buttons_frame.pack(fill="x", padx=5, pady=5)
        
        # Tạo các nút chuyển động camera
        row, col = 0, 0
        for move in self.camera_moves:
            btn = ttk.Button(
                camera_buttons_frame, 
                text=move,
                command=lambda m=move: self.insert_camera_move(m)
            )
            btn.grid(row=row, column=col, padx=3, pady=3, sticky="ew")
            
            col += 1
            if col > 4:  # 5 nút mỗi hàng
                col = 0
                row += 1
        
        # Thư viện Prompt
        library_frame = ttk.LabelFrame(main_frame, text="Thư viện Prompt")
        library_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Panel bên trái - Danh mục
        left_panel = ttk.Frame(library_frame)
        left_panel.pack(side="left", fill="y", padx=(0, 5))
        
        ttk.Label(left_panel, text="Danh mục:").pack(anchor="w")
        self.category_listbox = tk.Listbox(left_panel, width=20, height=10)
        self.category_listbox.pack(fill="y", expand=True)
        self.category_listbox.bind('<<ListboxSelect>>', self.on_category_select)
        
        for category in self.prompt_library.categories:
            self.category_listbox.insert(tk.END, category)
        
        # Panel phải - Prompt trong danh mục
        right_panel = ttk.Frame(library_frame)
        right_panel.pack(side="right", fill="both", expand=True)
        
        ttk.Label(right_panel, text="Prompt:").pack(anchor="w")
        self.prompt_listbox = tk.Listbox(right_panel, height=10)
        self.prompt_listbox.pack(fill="both", expand=True)
        self.prompt_listbox.bind('<<ListboxSelect>>', self.on_prompt_select)
        
        # Nút thêm prompt vào thư viện
        add_frame = ttk.Frame(right_panel)
        add_frame.pack(fill="x", pady=5)
        
        self.prompt_name_var = tk.StringVar()
        ttk.Label(add_frame, text="Tên:").pack(side="left")
        ttk.Entry(add_frame, textvariable=self.prompt_name_var).pack(side="left", fill="x", expand=True, padx=5)
        
        self.new_category_var = tk.StringVar()
        ttk.Label(add_frame, text="Danh mục mới:").pack(side="left", padx=(10, 0))
        ttk.Entry(add_frame, textvariable=self.new_category_var, width=15).pack(side="left", padx=5)
        
        ttk.Button(add_frame, text="Lưu vào thư viện", command=self.save_to_library).pack(side="right")
        
        # Trình soạn thảo Prompt
        editor_frame = ttk.LabelFrame(main_frame, text="Soạn thảo Prompt")
        editor_frame.pack(fill="both", expand=True)
        
        self.prompt_editor = tk.Text(editor_frame, wrap="word", height=10)
        self.prompt_editor.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Nếu có prompt ban đầu, hiển thị trong editor
        if self.initial_prompt:
            self.prompt_editor.insert("1.0", self.initial_prompt)
        
        # Các nút hành động
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Button(buttons_frame, text="Hủy", command=self.top.destroy).pack(side="right", padx=5)
        ttk.Button(buttons_frame, text="Áp dụng", command=self.apply_prompt).pack(side="right")
    
    def insert_camera_move(self, move):
        """Chèn chuyển động camera vào prompt"""
        self.prompt_editor.insert(tk.INSERT, f"[{move}] ")
        self.prompt_editor.focus_set()
    
    def on_category_select(self, event):
        """Xử lý khi chọn danh mục"""
        self.prompt_listbox.delete(0, tk.END)
        
        selection = self.category_listbox.curselection()
        if not selection:
            return
            
        index = selection[0]
        category = self.category_listbox.get(index)
        
        prompts = self.prompt_library.get_prompts_by_category(category)
        for prompt in prompts:
            self.prompt_listbox.insert(tk.END, prompt["name"])
    
    def on_prompt_select(self, event):
        """Xử lý khi chọn prompt từ thư viện"""
        category_selection = self.category_listbox.curselection()
        prompt_selection = self.prompt_listbox.curselection()
        
        if not category_selection or not prompt_selection:
            return
            
        category_index = category_selection[0]
        prompt_index = prompt_selection[0]
        
        category = self.category_listbox.get(category_index)
        prompt_name = self.prompt_listbox.get(prompt_index)
        
        prompts = self.prompt_library.get_prompts_by_category(category)
        for prompt in prompts:
            if prompt["name"] == prompt_name:
                # Hiển thị prompt trong editor
                self.prompt_editor.delete("1.0", tk.END)
                self.prompt_editor.insert("1.0", prompt["prompt"])
                self.prompt_name_var.set(prompt_name)
                break
    
    def save_to_library(self):
        """Lưu prompt hiện tại vào thư viện"""
        prompt_text = self.prompt_editor.get("1.0", tk.END).strip()
        prompt_name = self.prompt_name_var.get().strip()
        
        if not prompt_text or not prompt_name:
            messagebox.showwarning("Thông báo", "Vui lòng nhập tên và nội dung prompt.")
            return
        
        # Xác định danh mục
        category = None
        new_category = self.new_category_var.get().strip()
        
        if new_category:
            category = new_category
        else:
            selection = self.category_listbox.curselection()
            if selection:
                category = self.category_listbox.get(selection[0])
            else:
                category = "Khác"  # Danh mục mặc định
        
        # Lưu vào thư viện
        self.prompt_library.add_prompt(category, prompt_name, prompt_text)
        
        # Cập nhật danh sách danh mục
        self.category_listbox.delete(0, tk.END)
        for cat in self.prompt_library.categories:
            self.category_listbox.insert(tk.END, cat)
        
        # Chọn danh mục vừa sử dụng
        for i, cat in enumerate(self.prompt_library.categories):
            if cat == category:
                self.category_listbox.selection_set(i)
                self.on_category_select(None)
                break
        
        # Thông báo thành công
        messagebox.showinfo("Thông báo", f"Đã lưu prompt '{prompt_name}' vào danh mục '{category}'.")
    
    def apply_prompt(self):
        """Áp dụng prompt và đóng cửa sổ"""
        prompt_text = self.prompt_editor.get("1.0", tk.END).strip()
        
        if self.callback:
            self.callback(prompt_text)
        
        self.top.destroy()


class MiniMaxVideoGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MiniMax Video Generator")
        self.root.geometry("900x700")
        
        # Khởi tạo các thành phần
        self.config = ConfigManager()
        self.api_client = MiniMaxAPI(self.config.api_key)
        self.excel_processor = ExcelProcessor()
        self.task_queue = TaskQueueManager(
            self.api_client, 
            max_concurrent_tasks=self.config.max_concurrent_tasks
        )
        
        # Thiết lập callbacks
        self.task_queue.on_task_completed = self.on_task_completed
        self.task_queue.on_task_failed = self.on_task_failed
        self.task_queue.on_task_started = self.on_task_started
        self.task_queue.on_queue_updated = self.update_queue_stats
        
        # Biến theo dõi
        self.images_list = []
        self.default_prompt = tk.StringVar(value="")
        
        # Tạo giao diện
        self.create_widgets()
        
        # Bắt đầu xử lý hàng đợi
        self.task_queue.start_processing()
    
    def create_widgets(self):
        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill="both", expand=True)
        
        # Frame cho các đầu vào
        self.input_frame = ttk.LabelFrame(self.main_frame, text="Cấu hình")
        self.input_frame.pack(fill="x", expand=False, padx=10, pady=5)
        
        # API Key
        ttk.Label(self.input_frame, text="API Key:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.api_key_var = tk.StringVar(value=self.config.api_key)
        ttk.Entry(self.input_frame, textvariable=self.api_key_var, width=40, show="*").grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # Thư mục ảnh
        ttk.Label(self.input_frame, text="Thư mục ảnh:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.image_folder = tk.StringVar()
        ttk.Entry(self.input_frame, textvariable=self.image_folder, width=40).grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(self.input_frame, text="Chọn", command=self.select_image_folder).grid(row=1, column=2, padx=5, pady=5)
        
        # File Excel
        ttk.Label(self.input_frame, text="File Excel:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.excel_file = tk.StringVar()
        ttk.Entry(self.input_frame, textvariable=self.excel_file, width=40).grid(row=2, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(self.input_frame, text="Chọn", command=self.select_excel_file).grid(row=2, column=2, padx=5, pady=5)
        
        # Thư mục đầu ra
        ttk.Label(self.input_frame, text="Thư mục đầu ra:").grid(row=3, column=0, sticky="w", padx=5, pady=5)
        self.output_folder = tk.StringVar(value=self.config.output_folder)
        ttk.Entry(self.input_frame, textvariable=self.output_folder, width=40).grid(row=3, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(self.input_frame, text="Chọn", command=self.select_output_folder).grid(row=3, column=2, padx=5, pady=5)
        
        # Số lượng video mỗi ảnh
        ttk.Label(self.input_frame, text="Số video mỗi ảnh:").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        self.videos_per_image = tk.IntVar(value=self.config.max_videos_per_image)
        ttk.Spinbox(self.input_frame, from_=1, to=5, textvariable=self.videos_per_image, width=5).grid(row=4, column=1, sticky="w", padx=5, pady=5)
        
        # Mô hình
        ttk.Label(self.input_frame, text="Mô hình:").grid(row=5, column=0, sticky="w", padx=5, pady=5)
        self.model_var = tk.StringVar(value=self.config.model)
        model_combo = ttk.Combobox(self.input_frame, textvariable=self.model_var, width=20)
        model_combo['values'] = ("I2V-01-Director", "T2V-01-Director", "I2V-01", "I2V-01-live", "T2V-01", "S2V-01")
        model_combo.grid(row=5, column=1, sticky="w", padx=5, pady=5)
        
        # Nút soạn thảo prompt nâng cao
        ttk.Button(
            self.input_frame,
            text="Soạn thảo Prompt nâng cao",
            command=self.open_prompt_editor
        ).grid(row=5, column=2, padx=5, pady=5)
        
        # Khởi tạo thư viện prompt
        self.prompt_library = PromptLibrary()
        
        # Nút lưu cấu hình
        ttk.Button(self.input_frame, text="Lưu cấu hình", command=self.save_config).grid(row=6, column=0, padx=5, pady=5)
        
        # Nút bắt đầu xử lý
        ttk.Button(self.input_frame, text="Bắt đầu tạo video", command=self.start_video_generation).grid(row=6, column=1, columnspan=2, sticky="e", padx=5, pady=5)
        
        # Thêm panel thống kê
        self.create_statistics_panel()
        
        # Frame danh sách ảnh
        images_frame = ttk.LabelFrame(self.main_frame, text="Danh sách ảnh")
        images_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.images_listbox = tk.Listbox(images_frame, height=10)
        self.images_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar = ttk.Scrollbar(images_frame, orient="vertical", command=self.images_listbox.yview)
        scrollbar.pack(side="right", fill="y", pady=5)
        self.images_listbox.config(yscrollcommand=scrollbar.set)
        self.images_listbox.bind('<<ListboxSelect>>', self.on_image_select)
        
        # Frame console log
        log_frame = ttk.LabelFrame(self.main_frame, text="Log")
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scrollbar.pack(side="right", fill="y", pady=5)
        self.log_text.config(yscrollcommand=log_scrollbar.set)
    
    def create_statistics_panel(self):
        """Tạo panel hiển thị thống kê"""
        stats_frame = ttk.LabelFrame(self.main_frame, text="Thống kê")
        stats_frame.pack(fill="x", expand=False, padx=10, pady=5)
        
        # Khởi tạo các biến theo dõi cho thống kê
        self.stats_vars = {
            'total_tasks': tk.StringVar(value="Tổng số task: 0"),
            'queued_tasks': tk.StringVar(value="Đang chờ: 0"),
            'active_tasks': tk.StringVar(value="Đang xử lý: 0"),
            'completed_tasks': tk.StringVar(value="Đã hoàn thành: 0"),
            'failed_tasks': tk.StringVar(value="Thất bại: 0"),
            'success_rate': tk.StringVar(value="Tỷ lệ thành công: 0%"),
            'avg_processing_time': tk.StringVar(value="Thời gian trung bình: --"),
            'estimated_completion_time': tk.StringVar(value="Ước tính hoàn thành: --")
        }
        
        # Tạo giao diện hiển thị thống kê
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.pack(fill="x", expand=True, padx=5, pady=5)
        
        # Cột 1
        ttk.Label(stats_grid, textvariable=self.stats_vars['total_tasks']).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(stats_grid, textvariable=self.stats_vars['queued_tasks']).grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(stats_grid, textvariable=self.stats_vars['active_tasks']).grid(row=2, column=0, sticky="w", padx=5, pady=2)
        
        # Cột 2
        ttk.Label(stats_grid, textvariable=self.stats_vars['completed_tasks']).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(stats_grid, textvariable=self.stats_vars['failed_tasks']).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(stats_grid, textvariable=self.stats_vars['success_rate']).grid(row=2, column=1, sticky="w", padx=5, pady=2)
        
        # Cột 3
        ttk.Label(stats_grid, textvariable=self.stats_vars['avg_processing_time']).grid(row=0, column=2, sticky="w", padx=5, pady=2)
        ttk.Label(stats_grid, textvariable=self.stats_vars['estimated_completion_time']).grid(row=1, column=2, sticky="w", padx=5, pady=2)
        
        # Thanh tiến trình tổng thể
        ttk.Label(stats_frame, text="Tiến trình tổng thể:").pack(anchor="w", padx=5, pady=(5,0))
        self.progress_bar = ttk.Progressbar(stats_frame, orient="horizontal", length=100, mode="determinate")
        self.progress_bar.pack(fill="x", padx=5, pady=(0,5))
        
        # Khởi tạo statistic manager
        self.stats_manager = TaskStatisticsManager(self.task_queue)
        
        # Bắt đầu cập nhật thống kê
        self.schedule_stats_update()
    
    def schedule_stats_update(self):
        """Đặt lịch cập nhật thống kê định kỳ"""
        self.update_statistics()
        self.root.after(2000, self.schedule_stats_update)
    
    def update_statistics(self):
        """Cập nhật thông tin thống kê"""
        stats = self.stats_manager.update_stats()
        
        self.stats_vars['total_tasks'].set(f"Tổng số task: {stats['total_tasks']}")
        self.stats_vars['queued_tasks'].set(f"Đang chờ: {stats['queued_tasks']}")
        self.stats_vars['active_tasks'].set(f"Đang xử lý: {stats['active_tasks']}")
        self.stats_vars['completed_tasks'].set(f"Đã hoàn thành: {stats['completed_tasks']}")
        self.stats_vars['failed_tasks'].set(f"Thất bại: {stats['failed_tasks']}")
        self.stats_vars['success_rate'].set(f"Tỷ lệ thành công: {stats['success_rate']:.1f}%")
        
        avg_time = stats['avg_processing_time']
        if avg_time is not None:
            if avg_time > 60:
                self.stats_vars['avg_processing_time'].set(f"Thời gian TB: {avg_time/60:.1f} phút")
            else:
                self.stats_vars['avg_processing_time'].set(f"Thời gian TB: {avg_time:.1f} giây")
        
        est_time = stats['estimated_completion_time']
        if est_time is not None:
            if est_time > 3600:
                self.stats_vars['estimated_completion_time'].set(f"Ước tính: {est_time/3600:.1f} giờ")
            elif est_time > 60:
                self.stats_vars['estimated_completion_time'].set(f"Ước tính: {est_time/60:.1f} phút")
            else:
                self.stats_vars['estimated_completion_time'].set(f"Ước tính: {est_time:.0f} giây")
        
        # Cập nhật thanh tiến trình
        if stats['total_tasks'] > 0:
            progress = (stats['completed_tasks'] + stats['failed_tasks']) / stats['total_tasks'] * 100
            self.progress_bar['value'] = progress
    
    def select_image_folder(self):
        """Chọn thư mục chứa ảnh"""
        folder = filedialog.askdirectory(title="Chọn thư mục ảnh")
        if folder:
            self.image_folder.set(folder)
            self.load_images_from_folder(folder)
    
    def select_excel_file(self):
        """Chọn file Excel chứa prompt"""
        file = filedialog.askopenfilename(
            title="Chọn file Excel", 
            filetypes=[("Excel files", "*.xlsx *.xls")]
        )
        if file:
            self.excel_file.set(file)
            if self.excel_processor.load_excel(file):
                self.log(f"Đã tải file Excel: {file}")
            else:
                messagebox.showerror("Lỗi", "Không thể tải file Excel. Vui lòng kiểm tra định dạng.")
    
    def select_output_folder(self):
        """Chọn thư mục đầu ra cho video"""
        folder = filedialog.askdirectory(title="Chọn thư mục đầu ra")
        if folder:
            self.output_folder.set(folder)
    
    def load_images_from_folder(self, folder_path):
        """Tải danh sách ảnh từ thư mục"""
        self.images_list = []
        self.images_listbox.delete(0, tk.END)
        
        if not os.path.isdir(folder_path):
            return
        
        for file in os.listdir(folder_path):
            if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                image_path = os.path.join(folder_path, file)
                self.images_list.append(image_path)
                self.images_listbox.insert(tk.END, os.path.basename(image_path))
        
        self.log(f"Đã tìm thấy {len(self.images_list)} ảnh trong thư mục")
    
    def on_image_select(self, event):
        """Xử lý khi chọn ảnh từ danh sách"""
        selection = self.images_listbox.curselection()
        if not selection:
            return
            
        index = selection[0]
        image_path = self.images_list[index]
        
        # Lấy prompt nếu có
        if self.excel_processor.data is not None:
            prompt = self.excel_processor.get_prompt_for_image(image_path)
            if prompt:
                self.log(f"Prompt cho ảnh {os.path.basename(image_path)}: {prompt}")
    
    def save_config(self):
        """Lưu cấu hình"""
        self.config.api_key = self.api_key_var.get()
        self.config.output_folder = self.output_folder.get()
        self.config.max_videos_per_image = self.videos_per_image.get()
        self.config.model = self.model_var.get()
        
        self.config.save_config()
        
        # Cập nhật API client với key mới
        self.api_client = MiniMaxAPI(self.config.api_key)
        self.task_queue.api_client = self.api_client
        
        self.log("Đã lưu cấu hình")
        messagebox.showinfo("Thông báo", "Đã lưu cấu hình thành công!")
    
    def open_prompt_editor(self, prompt_text=""):
        """Mở cửa sổ soạn thảo prompt nâng cao"""
        current_prompt = prompt_text
        if not current_prompt and self.excel_processor.data is not None:
            # Lấy prompt từ Excel của ảnh đang chọn nếu có
            selected_image = self.get_selected_image()
            if selected_image:
                current_prompt = self.excel_processor.get_prompt_for_image(selected_image) or ""
        
        PromptEditorWindow(self.root, self.prompt_library, current_prompt, self.apply_edited_prompt)
    
    def apply_edited_prompt(self, prompt_text):
        """Áp dụng prompt đã chỉnh sửa"""
        selected_image = self.get_selected_image()
        if selected_image and self.excel_processor.data is not None:
            # Cập nhật prompt trong Excel
            self.excel_processor.update_prompt_for_image(selected_image, prompt_text)
            self.excel_processor.save_excel()
            self.log(f"Đã cập nhật prompt cho ảnh {os.path.basename(selected_image)}")
        else:
            # Lưu để sử dụng cho tất cả ảnh
            self.default_prompt.set(prompt_text)
            self.log(f"Đã đặt prompt mặc định mới")
    
    def get_selected_image(self):
        """Lấy đường dẫn ảnh đang được chọn"""
        selection = self.images_listbox.curselection()
        if selection:
            index = selection[0]
            return self.images_list[index]
        return None
    
    def start_video_generation(self):
        """Bắt đầu quá trình tạo video"""
        # Kiểm tra đầu vào
        image_folder = self.image_folder.get()
        excel_file = self.excel_file.get()
        output_folder = self.output_folder.get()
        
        if not image_folder or not os.path.isdir(image_folder):
            messagebox.showerror("Lỗi", "Vui lòng chọn thư mục ảnh hợp lệ.")
            return
        
        if not excel_file or not os.path.isfile(excel_file):
            messagebox.showerror("Lỗi", "Vui lòng chọn file Excel hợp lệ.")
            return
        
        # Đảm bảo thư mục đầu ra tồn tại
        if not output_folder:
            output_folder = os.path.join(os.path.expanduser("~"), "MiniMaxVideos")
            self.output_folder.set(output_folder)
        
        os.makedirs(output_folder, exist_ok=True)
        
        # Tải file Excel nếu chưa tải
        if self.excel_processor.data is None:
            if not self.excel_processor.load_excel(excel_file):
                messagebox.showerror("Lỗi", "Không thể tải file Excel.")
                return
        
        # Lấy các file ảnh từ thư mục nếu chưa tải
        if not self.images_list:
            self.load_images_from_folder(image_folder)
        
        if not self.images_list:
            messagebox.showerror("Lỗi", "Không tìm thấy file ảnh trong thư mục đã chọn.")
            return
        
        # Xử lý từng ảnh
        tasks_count = 0
        for image_path in self.images_list:
            image_filename = os.path.basename(image_path)
            prompt = self.excel_processor.get_prompt_for_image(image_path)
            
            if not prompt:
                self.log(f"Cảnh báo: Không tìm thấy prompt cho ảnh {image_filename}, bỏ qua.")
                continue
            
            # Thêm task cho ảnh này dựa trên số lượng video mỗi ảnh
            for i in range(self.videos_per_image.get()):
                output_filename = os.path.join(
                    output_folder,
                    f"{os.path.splitext(image_filename)[0]}_video_{i+1}.mp4"
                )
                
                self.task_queue.add_task(
                    image_path=image_path,
                    prompt=prompt,
                    output_filename=output_filename,
                    model=self.model_var.get()
                )
                
                tasks_count += 1
                self.log(f"Đã thêm task cho ảnh {image_filename} ({i+1}/{self.videos_per_image.get()})")
        
        self.log(f"Đã thêm {tasks_count} task tạo video vào hàng đợi.")
        messagebox.showinfo("Thành công", f"Đã thêm {tasks_count} task tạo video vào hàng đợi.")
    
    def on_task_started(self, task_info):
        """Xử lý khi task bắt đầu"""
        image_basename = os.path.basename(task_info['image_path'])
        self.log(f"Bắt đầu tạo video cho ảnh {image_basename} (Task ID: {task_info['task_id']})")
    
    def on_task_completed(self, task_info):
        """Xử lý khi task hoàn thành"""
        image_basename = os.path.basename(task_info['image_path'])
        output_basename = os.path.basename(task_info['output_filename'])
        self.log(f"Đã hoàn thành và tải xuống video cho ảnh {image_basename}: {output_basename}")
    
    def on_task_failed(self, task_info):
        """Xử lý khi task thất bại"""
        image_basename = os.path.basename(task_info['image_path'])
        error = task_info.get('error', 'Lỗi không xác định')
        self.log(f"Lỗi khi tạo video cho ảnh {image_basename}: {error}")
    
    def update_queue_stats(self):
        """Cập nhật thông tin hàng đợi"""
        # Được gọi thông qua phương thức update_statistics
        pass
    
    def log(self, message):
        """Ghi log vào console"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)  # Cuộn xuống dòng cuối cùng
        logging.info(message)


def main():
    root = tk.Tk()
    
    try:
        # Đặt biểu tượng cho ứng dụng nếu có
        icon_path = resource_path('app_icon.ico')
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
    except Exception as e:
        logging.warning(f"Không thể tải biểu tượng ứng dụng: {e}")
    
    app = MiniMaxVideoGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
