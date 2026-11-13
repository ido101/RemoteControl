import socket
import pyautogui
import struct
import time
import io
import threading
import ssl
import os
from pathlib import Path
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Controller as MouseController, Button

DEFAULT_CONTROL_PORT = 8080
DEFAULT_SCREEN_PORT = 8081
DEFAULT_SLEEP = 0.3 # Lower for a smoother screen sharing

class ClientControlled:
    def __init__(self, host, port_control=DEFAULT_CONTROL_PORT, port_screen=DEFAULT_SCREEN_PORT, sleep_time=DEFAULT_SLEEP):
        self.host = host
        self.port_control = port_control
        self.port_screen = port_screen
        self.sleep_time = sleep_time
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.client_socket = None
        self.client_screen = None
        self.is_keyboard = False
        self.is_screen = False

    def create_client(self):
        self.client_socket = socket.socket() # Create raw TCP socket
        try:
            self.client_socket.connect((self.host, self.port_control))
            self.is_keyboard = True
        except Exception as e:
            print(f"Couldnt connect to keyboard: {e}")
        
    def create_screen_client(self):
        self.client_screen = socket.socket() # Create TCP socket
        try:
            self.client_screen.connect((self.host, self.port_screen))
            self.is_screen = True
        except Exception as e:
            print(f"Couldnt connect to screen: {e}")

    def wrap_client(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        self.client_socket = context.wrap_socket(self.client_socket)

    def wrap_screen_client(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        self.client_screen = context.wrap_socket(self.client_screen)

    def send_screen(self):
        if self.is_screen:
            try:
                while True:
                    screenshot = pyautogui.screenshot()
            
                    # Encode the frame:
                    frame_buffer = io.BytesIO()
                    screenshot.save(frame_buffer, format="JPEG", quality=70)
                    frame_data = frame_buffer.getvalue()
            
                    # Sends the size of the frame:
                    frame_size = len(frame_data)
                    self.client_screen.sendall(struct.pack('>L', frame_size))    
            
                    # Send the frame
                    self.client_screen.sendall(frame_data)
            
                    time.sleep(self.sleep_time) # For a quicker screenshot rate lower this number
            except Exception as e:
                print(f"Error while sending screenshot: {e}")
            finally:
                if self.client_screen:
                    self.client_screen.close()

    def send_keys(self):
        if self.is_keyboard:
            try:
                file = self.client_socket.makefile('r', buffering=1)
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    
                    info = line.split("|")
                    action = info[0]

                    if action == "click":
                        btn_name = info[1]
                        pressed = info[2] == "True"
                        
                        # Map string to pynput Button
                        btn = getattr(Button, btn_name, Button.left)
                        if pressed:
                            self.mouse.press(btn)
                        else:
                            self.mouse.release(btn)

                    elif action == "scroll":
                        self.mouse.scroll(int(info[1]), int(info[2]))

                    elif action == "move":
                        self.mouse.position = (int(info[1]), int(info[2]))

                    elif action == "key":
                        key_name = info[1]
                        self.keyboard.press(key_name)
                        self.keyboard.release(key_name)
                        print(f"clicked: {key_name}")

                    elif action == "special_key":
                        key_name = info[1]
                        if hasattr(Key, key_name):
                            key = getattr(Key, key_name)
                            self.keyboard.press(key)
                            self.keyboard.release(key)
                            print(f"clicked: {str(key)[4:]}")
            except Exception as e:
                print(f"Connection Lost: {e}")
            finally:
                if self.client_socket:
                    self.client_socket.close()
                print("Client Disconnected")

    def run(self):
        try:
            self.create_client()
            self.wrap_client()
            print("Client Connected")

            file = self.client_socket.makefile('r', buffering=1)
            choice = file.readline().strip()
            print(f"Configuration received from server: {choice}")

            

            threads = []
            if "1" in choice or "2" in choice:
                thread_key = threading.Thread(target=self.send_keys)
                thread_key.start()
                threads.append(thread_key)
                
            if "3" in choice:
                self.create_screen_client()
                self.wrap_screen_client()
                thread_screen = threading.Thread(target=self.send_screen)
                thread_screen.start()
                threads.append(thread_screen)

            for thread in threads:
                thread.join()
        except Exception as e:
            print(f"Error during client loop: {e}")
        


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent) # Change directory to where the file is

    ip = input("Enter IP of the server: ")
    
    clnt = ClientControlled(ip, 8080, 8081)
    
    clnt.run()