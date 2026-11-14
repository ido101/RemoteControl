import msvcrt
import socket
import threading
import time
import struct
import io
import cv2
import numpy as np
import ssl
import os
from pathlib import Path
from PIL import Image
from pynput.keyboard import Listener as KeyboardListener
from pynput import mouse

DEFAULT_CONTROL_PORT = 8080
DEFAULT_SCREEN_PORT = 8081
DEFAULT_MOUSE_INTERVAL = 0.05 # Lower for a smoother mouse movement
CHUNK_SIZE = 1024

class RemoteServer:
    def __init__(self, host, port_control=DEFAULT_CONTROL_PORT, port_screen=DEFAULT_SCREEN_PORT, mouse_interval=DEFAULT_MOUSE_INTERVAL, chunk_size=CHUNK_SIZE):
        self.input_control = InputController(mouse_interval)
        self.net_manager = NetworkManager(host, port_control, port_screen)
        self.screen_stream = ScreenStreamer(chunk_size)

    def start_keyboard_thread(self):
        t_keyboard = threading.Thread(target= self.input_control.keyboard_thread, args=(self.net_manager.client_socket,))
        t_keyboard.start()
        return t_keyboard

    def start_mouse_thread(self):
        t_mouse = threading.Thread(target= self.input_control.mouse_thread, args=(self.net_manager.client_socket,))
        t_mouse.start()
        return t_mouse

    def start_screen_thread(self):
        t_screen = threading.Thread(target= self.screen_stream.screen_thread, args=(self.net_manager.client_screen_socket,))
        t_screen.start()
        return t_screen

    def start_monitor_thread(self):
        t_monitor = threading.Thread(target= self.connection_monitor)
        t_monitor.start()
        return t_monitor

    def stop_listeners(self):
        if self.input_control.keyboard_listener:
            self.input_control.keyboard_listener.stop()
        if self.input_control.mouse_listener:
            self.input_control.mouse_listener.stop()

    def connection_monitor(self):
        try:
            while True:
                data = self.net_manager.client_socket.recv(1)
                if not data:
                    break
        except Exception as e:
            print(f"Error during connection monitoring: {e}")

        print("\nClient disconnected!")
        
        # Stop listeners so join() unblocks immediately
        self.stop_listeners()
    
    def run(self):
        print("--------------Remote Control--------------")
        exiting = False
        while True:
            try:
                self.net_manager.create_server()
                print(f"Listening for new devices to control...")

                client_address = self.net_manager.accept_client()
                self.net_manager.wrap_client_ssl()
                print(f"Control established with {client_address}")
                
                while msvcrt.kbhit():
                    msvcrt.getch()
                choice = input("Do you want control over keyboard(1), mouse(2), or screen(3)?\n(To let go of this connection - l, to quit - q)\nType all the options you want: ").strip().lower()

                self.net_manager.client_socket.sendall(choice.encode() + b'\n')

                if "q" in choice:
                    exiting = True
                    exit()

                if "l" in choice:
                    self.net_manager.close_sockets()
                    continue

                threads = []
                if "1" in choice:
                    thread_keyboard = self.start_keyboard_thread()
                    threads.append(thread_keyboard)
                if "2" in choice:
                    thread_mouse = self.start_mouse_thread()
                    threads.append(thread_mouse)
                if "3" in choice:
                    self.net_manager.create_screen_server()
                    self.net_manager.accept_screen_client()
                    thread_screen = self.start_screen_thread()
                    threads.append(thread_screen)

                thread_monitor = self.start_monitor_thread()
                threads.append(thread_monitor)
    
                for thread in threads:
                    if thread:
                        thread.join()
    
                print("Threads finished. Connection closed.")
            except Exception as e:
                print(f"Error in server loop: {e}")
            finally:
                self.net_manager.close_sockets()
                if not exiting:
                    print("Restarting server for next connection...\n")
                else:
                    print("Exiting...")

class NetworkManager:
    def __init__(self, host, port_control, port_screen):
        self.host = host
        self.port_control = port_control
        self.port_screen = port_screen
        self.server_socket = None
        self.client_socket = None
        self.server_screen_socket = None
        self.client_screen_socket = None

    def create_server(self):
        self.server_socket = socket.socket()
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port_control))
        self.server_socket.listen(5)
    
    def accept_client(self):
        self.client_socket, client_address = self.server_socket.accept()
        return client_address

    def wrap_client_ssl(self):
        # Create SSL Server context
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile="server.crt", keyfile="server.key")

        # Wrap the socket through SSL
        self.client_socket = context.wrap_socket(self.client_socket, server_side=True)

    def create_screen_server(self):
        self.server_screen_socket = socket.socket()
        self.server_screen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_screen_socket.bind((self.host, self.port_screen))
        self.server_screen_socket.listen(5)

    def accept_screen_client(self):
        raw_screen_socket, client_address = self.server_screen_socket.accept()

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile="server.crt", keyfile="server.key")

        self.client_screen_socket = context.wrap_socket(raw_screen_socket, server_side=True)
        return client_address
    
    def close_sockets(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
            
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None

        if self.client_screen_socket:
            try:
                self.client_screen_socket.close()
            except:
                pass
            self.client_screen_socket = None

        if self.server_screen_socket:
            try:
                self.server_screen_socket.close()
            except:
                pass
            self.server_screen_socket = None

class InputController:
    def __init__(self, mouse_interval=DEFAULT_MOUSE_INTERVAL):
        self.mouse_interval = mouse_interval
        self.keyboard_listener = None
        self.mouse_listener = None

    def keyboard_thread(self, client_socket):
        def send_keyboard_click(key):
            try:
                if hasattr(key, 'char') and key.char:
                    message = f"key|{key.char}\n"
                    client_socket.send(message.encode())
                    print(f"sent: {key}")
                # Check for a special key(backspace, space, enter, tab)
                elif hasattr(key, "name") and key.name:
                    message = f"special_key|{key.name}\n"
                    client_socket.send(message.encode())
                    print(f"sent: {key.name}")
            except (ConnectionResetError, BrokenPipeError, OSError):
                print("[!] Client disconnected during keyboard event.")
                client_socket.close()
                return False
            except Exception as e:
                print(f"Keyboard error: {e}")
                return False
        # Collect events until released
        with KeyboardListener(on_press=send_keyboard_click) as listener:
            self.keyboard_listener = listener
            listener.join()

    def mouse_thread(self, client_socket):
        last_sent = 0

        def on_move(x, y):
            # Make mouse movement with intervals to avoid overloading sockets (Commenting this part will make for a smoother mouse movement)
            nonlocal last_sent
            current_time = time.time()
            if current_time - last_sent < self.mouse_interval:
                return
            last_sent = current_time
            try:
                message = f"move|{x}|{y}\n"
                client_socket.send(message.encode())
                # print("Mouse moved to ({0}, {1})".format(x, y))
            except (ConnectionResetError, BrokenPipeError, OSError):
                print("[!] Client disconnected during mouse movement.")
                client_socket.close()
                return False # Returning False stops the pynput listener
        
        def on_click(x, y, button, pressed):
            try:
                # Send button name (e.g., 'left', 'right') and pressed state
                btn_name = button.name if hasattr(button, 'name') else 'left'
                message = f"click|{btn_name}|{pressed}\n"
                client_socket.send(message.encode())
            except (ConnectionResetError, BrokenPipeError, OSError):
                print("[!] Client disconnected during mouse activity.")
                client_socket.close()
                return False # Returning False stops the pynput listener

        def on_scroll(x, y, dx, dy):
            try:
                message = f"scroll|{dx}|{dy}\n"
                client_socket.send(message.encode())
                # print('Mouse scrolled at ({0}, {1})({2}, {3})'.format(x, y, dx, dy))
            except (ConnectionResetError, BrokenPipeError, OSError):
                print("[!] Client disconnected during mouse movement.")
                client_socket.close()
                return False # Returning False stops the pynput listener

        with mouse.Listener(on_click = on_click, on_scroll=on_scroll, on_move=on_move) as listener:
            self.mouse_listener = listener
            listener.join()

class ScreenStreamer:
    def __init__(self, chunk_size):
        self.chunk_size = chunk_size

    def screen_thread(self, client_screen_socket):
        try:
            # Create Window
            cv2.namedWindow('Remote Screen', cv2.WINDOW_NORMAL)
            cv2.setWindowProperty('Remote Screen', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN) # Make it fullscreen
            
            is_finished = False
            while True:
                size = b""
                while len(size) < 4:
                    packet = client_screen_socket.recv(4)
                    if not packet:
                        print("Client disconnected.")
                        is_finished = True
                        break
                    size += packet
                if is_finished:
                    break
                frame_size = struct.unpack('>L', size)[0]

                data = b""
                while len(data) < frame_size:
                    remaining = frame_size - len(data)
                    ch_size = min(self.chunk_size, remaining)
                    packet = client_screen_socket.recv(ch_size)
                    if not packet:  # Client disconnected or connection dropped!
                        print("Client disconnected.")
                        is_finished = True
                        break
                    data += packet
                if is_finished:
                    break
                
                frame_data = io.BytesIO(data)
                frame = Image.open(frame_data)
                frame = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
                
                # Display the frame
                cv2.imshow('Remote Screen', frame)
                cv2.waitKey(1)
                # In order to use ESC to close:
                # if cv2.waitKey(1) == 27:
                #   break
        except Exception as e:
            print("Screen Thread Error [!]")
        finally:
            cv2.destroyAllWindows()


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent) # Change directory to where the file is
    
    # Computer's local ip
    local_ip = get_ip()
    print(f"IP Address found: {local_ip}")

    serv = RemoteServer(local_ip, 8080, 8081)
    serv.run()