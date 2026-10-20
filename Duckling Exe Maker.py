import os
import sys
import subprocess
import shutil

# Automatically set working directory to script location to avoid system32 permission errors
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, 
    QPushButton, QTextEdit, QFileDialog, QVBoxLayout, QHBoxLayout, 
    QGroupBox, QMessageBox, QSplitter, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PIL import Image

DEFAULT_LICENSE = """MIT License

Copyright (c) 2026 Program Creator

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

class BuildWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, app_name, version, publisher, script_path, image_path, license_text):
        super().__init__()
        self.app_name = app_name
        self.clean_app_name = app_name.replace(" ", "")
        self.version = version
        self.publisher = publisher
        self.script_path = script_path
        self.image_path = image_path
        self.license_text = license_text

    def run(self):
        try:
            # 1. Create dedicated output directory for this app
            project_dir = os.path.join(os.getcwd(), self.clean_app_name)
            if not os.path.exists(project_dir):
                os.makedirs(project_dir)
            
            output_installer_dir = os.path.join(project_dir, 'output_installer')
            if not os.path.exists(output_installer_dir):
                os.makedirs(output_installer_dir)
            
            self.progress_signal.emit(10, f"Created project workspace: {project_dir}")

            # 2. Convert Image to ICO
            ico_file = ""
            if self.image_path and os.path.exists(self.image_path):
                ico_file = os.path.join(project_dir, f"{self.clean_app_name}.ico")
                img = Image.open(self.image_path)
                img.save(ico_file, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
                self.progress_signal.emit(25, f"Converted app icon successfully.")

            # 3. Save License File
            license_file = os.path.join(project_dir, f"{self.clean_app_name}_license.txt")
            with open(license_file, "w", encoding="utf-8") as f:
                f.write(self.license_text)
            self.progress_signal.emit(40, "Generated customizable license file.")

            # 4. Compile Python Script to EXE via PyInstaller inside the workspace
            cmd = [
                sys.executable,
                "-m",
                "PyInstaller",
                "--onefile",
                "--windowed",
                f"--distpath={os.path.join(project_dir, 'dist')}",
                f"--workpath={os.path.join(project_dir, 'build')}",
                f"--specpath={project_dir}",
                f"--name={self.clean_app_name}"
            ]
            if ico_file and os.path.exists(ico_file):
                cmd.append(f"--icon={ico_file}")
            cmd.append(self.script_path)

            self.progress_signal.emit(50, "Running PyInstaller compilation...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
            for line in process.stdout:
                self.progress_signal.emit(50, line.strip())
            process.wait()

            if process.returncode != 0:
                self.finished_signal.emit(False, project_dir, "PyInstaller compilation failed.")
                return

            built_exe = os.path.join(project_dir, "dist", f"{self.clean_app_name}.exe")
            self.progress_signal.emit(70, f"Compiled standalone binary at {built_exe}")

            # 5. Generate Inno Setup Script (.iss) with properly doubled curly braces for AppId
            app_id = f"{{{{{self.clean_app_name}-GUID}}}}"
            iss_path = os.path.join(project_dir, f"{self.clean_app_name}_installer.iss")
            
            iss_template = """[Setup]
AppId={app_id}
AppName={app_name}
AppVersion={version}
AppPublisher={publisher}
DefaultDirName={{autopf}}\\{clean_app_name}
DefaultGroupName={app_name}
AllowNoIcons=yes
LicenseFile={license_file}
OutputDir=output_installer
OutputBaseFilename={clean_app_name}_v{version}_Setup
Compression=lzma
SolidCompression=yes
SetupIconFile={ico_file}
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{built_exe}"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{license_file}"; DestDir: "{{app}}"; Flags: ignoreversion

[Icons]
Name: "{{group}}\\{app_name}"; Filename: "{{app}}\\{clean_app_name}.exe"; IconFilename: "{ico_file}"
Name: "{{group}}\\{{cm:UninstallProgram,{app_name}}}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\{app_name}"; Filename: "{{app}}\\{clean_app_name}.exe"; IconFilename: "{ico_file}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"; Flags: unchecked

[Run]
Filename: "{{app}}\\{clean_app_name}.exe"; Description: "{{cm:LaunchProgram,{app_name}}}"; Flags: nowait postinstall skipifsilent
"""
            
            iss_content = iss_template.format(
                app_id=app_id,
                app_name=self.app_name,
                clean_app_name=self.clean_app_name,
                version=self.version,
                publisher=self.publisher,
                license_file=license_file,
                built_exe=built_exe,
                ico_file=ico_file
            )

            with open(iss_path, "w", encoding="utf-8") as f:
                f.write(iss_content)

            self.progress_signal.emit(85, "Generated Inno Setup script (.iss). Compiling setup installer...")

            # 6. Automatically compile the .iss file using Inno Setup (ISCC.exe)
            inno_paths = [
                r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                r"C:\Program Files\Inno Setup 6\ISCC.exe"
            ]
            iscc_exe = next((p for p in inno_paths if os.path.exists(p)), None)

            if not iscc_exe:
                self.finished_signal.emit(False, project_dir, "Inno Setup compiler (ISCC.exe) not found! Please install Inno Setup 6 so setup .exes can be generated.")
                return

            inno_process = subprocess.Popen([iscc_exe, iss_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
            for line in inno_process.stdout:
                self.progress_signal.emit(90, line.strip())
            inno_process.wait()

            if inno_process.returncode != 0:
                self.finished_signal.emit(False, project_dir, "Inno Setup compilation failed.")
                return

            self.progress_signal.emit(100, f"Setup installer compiled successfully!")
            self.finished_signal.emit(True, project_dir, f"Build complete! Setup installer ready inside 'output_installer'.")

        except Exception as e:
            self.finished_signal.emit(False, "", str(e))

class ProgramMakerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Duckling Program & Installer Maker")
        self.resize(950, 800)
        self.last_output_dir = ""
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # --- Top Form Container ---
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)

        # App Metadata Group
        meta_group = QGroupBox("Application Metadata")
        meta_layout = QVBoxLayout()
        
        self.app_name_input = QLineEdit()
        self.app_name_input.setPlaceholderText("e.g. MyAwesomeApp")
        meta_layout.addWidget(QLabel("Application Name:"))
        meta_layout.addWidget(self.app_name_input)

        self.version_input = QLineEdit("1.0.0")
        meta_layout.addWidget(QLabel("Version:"))
        meta_layout.addWidget(self.version_input)

        self.publisher_input = QLineEdit("Developer")
        meta_layout.addWidget(QLabel("Publisher / Developer:"))
        meta_layout.addWidget(self.publisher_input)
        meta_group.setLayout(meta_layout)
        form_layout.addWidget(meta_group)

        # File Selection Group
        file_group = QGroupBox("Files & Assets")
        file_layout = QVBoxLayout()

        script_layout = QHBoxLayout()
        self.script_input = QLineEdit()
        self.script_input.setPlaceholderText("Path to main .py script")
        script_btn = QPushButton("Browse Script")
        script_btn.clicked.connect(self.browse_script)
        script_layout.addWidget(self.script_input)
        script_layout.addWidget(script_btn)
        file_layout.addWidget(QLabel("Source Python Script:"))
        file_layout.addLayout(script_layout)

        icon_layout = QHBoxLayout()
        self.icon_input = QLineEdit()
        self.icon_input.setPlaceholderText("Path to icon image (PNG, JPG, WEBP)")
        icon_btn = QPushButton("Browse Image")
        icon_btn.clicked.connect(self.browse_icon)
        icon_layout.addWidget(self.icon_input)
        icon_layout.addWidget(icon_btn)
        file_layout.addWidget(QLabel("App Icon Image (Auto-converts to .ico):"))
        file_layout.addLayout(icon_layout)

        file_group.setLayout(file_layout)
        form_layout.addWidget(file_group)

        # License Editor Group
        license_group = QGroupBox("Customizable License (EULA)")
        license_layout = QVBoxLayout()
        self.license_edit = QTextEdit()
        self.license_edit.setPlainText(DEFAULT_LICENSE)
        license_layout.addWidget(self.license_edit)
        license_group.setLayout(license_layout)
        form_layout.addWidget(license_group)

        # Progress Bar & Actions Layout
        action_layout = QHBoxLayout()
        self.build_btn = QPushButton("Build Installer & EXE Package")
        self.build_btn.setStyleSheet("font-weight: bold; font-size: 14px; padding: 10px;")
        self.build_btn.clicked.connect(self.start_build_process)
        
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.setStyleSheet("font-weight: bold; font-size: 14px; padding: 10px;")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self.open_output_folder)

        action_layout.addWidget(self.build_btn)
        action_layout.addWidget(self.open_folder_btn)
        form_layout.addLayout(action_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        form_layout.addWidget(self.progress_bar)

        splitter.addWidget(form_container)

        # --- Bottom Console Output Container ---
        console_group = QGroupBox("Build Console Log")
        console_layout = QVBoxLayout()
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace;")
        console_layout.addWidget(self.console_output)
        console_group.setLayout(console_layout)

        splitter.addWidget(console_group)
        splitter.setSizes([600, 180])

    def log(self, message):
        self.console_output.append(message)
        self.console_output.verticalScrollBar().setValue(
            self.console_output.verticalScrollBar().maximum()
        )

    def browse_script(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Python Script", "", "Python Files (*.py);;All Files (*.*)")
        if file_name:
            self.script_input.setText(file_name)

    def browse_icon(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Icon Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*.*)")
        if file_name:
            self.icon_input.setText(file_name)

    def start_build_process(self):
        app_name = self.app_name_input.text().strip()
        script_path = self.script_input.text().strip()
        image_path = self.icon_input.text().strip()
        version = self.version_input.text().strip()
        publisher = self.publisher_input.text().strip()
        license_text = self.license_edit.toPlainText()

        if not app_name or not script_path:
            QMessageBox.warning(self, "Missing Fields", "Please provide at least an Application Name and a Source Script path.")
            return

        self.build_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log(f"\n[*] Starting build sequence for: {app_name} (v{version})...")

        self.worker = BuildWorker(app_name, version, publisher, script_path, image_path, license_text)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.build_finished)
        self.worker.start()

    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.log(message)

    def build_finished(self, success, project_dir, message):
        self.build_btn.setEnabled(True)
        if success:
            self.last_output_dir = project_dir
            self.open_folder_btn.setEnabled(True)
            self.log(f"[SUCCESS] {message}")
            QMessageBox.information(self, "Build Complete", f"Successfully created your application setup installer!\nLocation: {project_dir}/output_installer")
        else:
            self.log(f"[-] Build Error: {message}")
            QMessageBox.critical(self, "Build Failed", message)

    def open_output_folder(self):
        if self.last_output_dir and os.path.exists(self.last_output_dir):
            os.startfile(self.last_output_dir)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # FIX: Import and apply qt_material AFTER QApplication is instantiated
    from qt_material import apply_stylesheet
    apply_stylesheet(app, theme='dark_teal.xml')
    
    window = ProgramMakerGUI()
    window.show()
    sys.exit(app.exec_())
