import sublime
import sublime_plugin
import threading
import zipfile
import os
import shutil

try:
    from . import requests
except:
    import requests

class updatepluginCommand(sublime_plugin.WindowCommand):
    def __init__(self, *args, **kwargs):
        super(updatepluginCommand, self).__init__(*args, **kwargs)

    def run(self):
        if not sublime.ok_cancel_dialog("Are you sure you want to update plugin?"):
            return

        # Open Console
        self.window.run_command("show_panel", 
            {"panel": "console", "toggle": False})

        # Start updating plugin
        handle_update_plugin(120)

def handle_update_plugin(timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return

        # Extract this zip file into temp
        print ("Extracting zip file......")
        zip_dir = "SublimeApex.zip"
        f = zipfile.ZipFile(zip_dir, 'r')
        f.extractall()
        f.close()

        # Move the extracted folder to packages path
        print ("Move extracted files to packages path......")
        print ("-" * 100)
        root_src_dir = "SublimeApex-master"
        root_dst_dir = sublime.packages_path() + "/SublimeApex"
        for src_dir, dirs, files in os.walk(root_src_dir):
            dst_dir = src_dir.replace(root_src_dir, root_dst_dir)
            if not os.path.exists(dst_dir):
                os.mkdir(dst_dir)
            for file_ in files:
                src_file = os.path.join(src_dir, file_)
                dst_file = os.path.join(dst_dir, file_)
                if os.path.exists(dst_file):
                    os.remove(dst_file)
                shutil.move(src_file, dst_dir)

        # After files in extract path are moved, 
        # just remove the path tree and the zipfile
        shutil.rmtree("SublimeApex-master")
        os.remove("SublimeApex.zip")

    # Get the newest plugin zip file in github
    print ("-" * 100)
    print ("Start to retrieve newest plugin zip file.....")
    thread = threading.Thread(target=retrieve_newest_zip, args=())
    thread.start()
    handle_thread(thread, timeout)

def retrieve_newest_zip():
    """
    Retrieve the newest SublimeApex Plugin zip file
    """

    r = requests.get("https://github.com/xjsender/SublimeApex/archive/master.zip", verify=False) 
    with open("SublimeApex.zip", "wb") as code:
        code.write(r.content)