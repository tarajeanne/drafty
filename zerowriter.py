import time
from math import floor

import keymaps
import socket
import shutil
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

delay = .100 #standard delay v2.2, 2.1 can use 0
font24 = ImageFont.truetype('./courier_prime.ttf', 24)

class Menu:
    def __init__(self, display_draw, epd, display_image):
        self.display_draw = display_draw
        self.epd = epd
        self.display_image = display_image
        self.menu_items = []
        self.selected_item = 0
        self.inputMode = False
        self.input_content = ""
        self.cursor_position = 0
        self.screenupdating = False
        self.inputlabel = "input"
        self.ending_content=""

    def addItem(self, text, action, callback):
        self.menu_items.append({'text': text, 'action': action, 'callback': callback})

    def up(self):
        self.selected_item -= 1
        if self.selected_item < 0:
            self.selected_item = len(self.menu_items) - 1
        self.display()
        time.sleep(delay)
    
    def down(self):
        self.selected_item += 1
        if self.selected_item > len(self.menu_items) - 1:
            self.selected_item = 0
        self.display()
        time.sleep(delay)

    def select(self):
        self.menu_items[self.selected_item]['action']()

    def display(self):

        self.display_draw.rectangle((0, 0, 800, 480), fill=255)
        y_position = 10
        
        start_index = max(0, self.selected_item - 5)  # Start index for display
        end_index = min(len(self.menu_items), start_index + 10)  # End index for display
        
        # Iterate over the range of menu items to display
        for index in range(start_index, end_index):
            prefix = self.selected_item == index and "> " or "  "  # Prefix for selected item
            item_text = self.menu_items[index]['text']  # Get the text of the menu item
            self.display_draw.text((10, y_position), prefix + item_text, font=font24, fill=0)
            y_position += 30  # Increment Y position for next menu item

        partial_buffer = self.epd.getbuffer(self.display_image)
        self.epd.display_Partial(partial_buffer)
        time.sleep(delay)

    def save_as(self):
        self.ending_content=""
        self.getInput("File Name", self.input_content)

    def delete_file(self):
        self.ending_content=""
        self.getInput("'delete' to confirm", self.input_content)

    def request_network_pw(self):
        self.ending_content=""
        self.getInput("PW", self.input_content)
        return

    def partial_update(self):
        self.display_draw.rectangle((0, 450, 800, 480), fill=255)  # Clear display
        temp_content = self.inputlabel + ": " + self.input_content + self.ending_content
        # Draw input line text
        self.display_draw.text((10, 450), str(temp_content), font=font24, fill=0)
        partial_buffer = self.epd.getbuffer(self.display_image)
        self.epd.display_Partial(partial_buffer)
        time.sleep(delay)

    def getInput(self, prompt, callback):
        self.inputMode = True
        self.input_content = ""
        self.cursor_position = 0
        self.inputlabel = prompt

    def cleanupInput(self):
        self.inputMode = False
        self.input_content=""
        time.sleep(delay) 
        self.display()

    def consolemsg(self, text):
        self.display_draw.rectangle((0, 0, 800, 480), fill=255)  # Clear display
        temp_content = text
        # Draw input line text
        self.display_draw.text((0, 150), str(temp_content), font=font24, fill=0)        
        partial_buffer = self.epd.getbuffer(self.display_image)
        self.epd.display_Partial(partial_buffer)
        time.sleep(delay)
        self.display_draw.rectangle((0, 0, 800, 480), fill=255)  # Clear display
        partial_buffer = self.epd.getbuffer(self.display_image)
        self.epd.display_Partial(partial_buffer)
        time.sleep(delay)

class ZeroWriter:
    def __init__(self):
        self.epd = None
        self.display_image = None
        self.display_draw = None
        self.display_updating = False
        self.cursor_position = 0
        self.text_content = ""
        self.input_content = ""
        self.needs_display_update = False
        bbox = font24.getbbox("A")
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        self.chars_per_line = floor(780 / width)
        self.lines_on_screen = floor(460 / height)
        self.line_spacing = floor(height * 1.6)
        self.scrollindex = 1
        self.console_message = ""
        self.typing_last_time = 0
        self.updating_input_area = False
        self.control_active = False
        self.shift_active = False
        self.menu_mode = False
        self.menu = None
        self.manual_network=""
        self.parent_menu = None # used to store the menu that was open before the load menu was opened
        self.server_address = "not active"
        self.current_file_path = None
        self.doReset = False

    def get_storage_dir(self):
        # Use the user's Documents folder to store files outside the app folder
        base = os.path.join(os.path.expanduser("~"), "Documents", "Drafty")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            # Fallback to home directory if Documents does not exist
            base = os.path.join(os.path.expanduser("~"), "Drafty")
            os.makedirs(base, exist_ok=True)
        return base

    def get_archive_dir(self):
        archive = os.path.join(self.get_storage_dir(), "archive")
        os.makedirs(archive, exist_ok=True)
        return archive

    def initialize(self):
        self.epd.init()
        self.epd.Clear()
        self.display_image = Image.new('1', (self.epd.width, self.epd.height), 255)
        self.display_draw = ImageDraw.Draw(self.display_image)
        self.last_display_update = time.time()

        self.keyboard.on_press(self.handle_key_press, suppress=True) #handles modifiers and shortcuts
        self.keyboard.on_release(self.handle_key_up, suppress=True)

        self.menu = Menu(self.display_draw, self.epd, self.display_image)
        self.populate_main_menu()

        self.load_menu = Menu(self.display_draw, self.epd, self.display_image)
        self.populate_load_menu()

        self.networks_menu = Menu(self.display_draw, self.epd, self.display_image)
        self.populate_networks_menu()

        #second init should catch if initial init has errors.
        time.sleep(.25)
        self.epd.init()
        self.epd.Clear()
        #self.check_nmcli()


    def get_ssid(self):
        try:
            raw_wifi = subprocess.check_output(['iwgetid', '-r'])
            data_strings = raw_wifi.decode('utf-8').split()
            return data_strings
        except Exception as e:
            return(e)
            print("error getting current SSID")

    def show_load_menu(self):
        self.parent_menu = self.menu
        self.populate_load_menu()
        self.menu = self.load_menu
        self.menu.display()

    def show_networks_menu(self):
        self.parent_menu = self.menu
        self.populate_networks_menu()
        self.menu = self.networks_menu
        self.menu.display()

    def hide_child_menu(self):
        self.menu = self.parent_menu
        self.populate_main_menu()
        self.menu.display()

    def populate_main_menu(self):
        self.menu.menu_items.clear()
        self.menu.addItem("Save As", lambda: self.menu.save_as(), lambda: self.save_as_file(self.menu.input_content))
        self.menu.addItem("New", lambda: self.new_file(), None)
        self.menu.addItem("Load", lambda: self.show_load_menu(), None)
        self.menu.addItem("", lambda: print(""), None)
        self.menu.addItem("Wifi: " + str(self.get_ssid()), lambda: self.show_networks_menu(), None)
        self.menu.addItem("Files: " + str(self.server_address), lambda: None, None)
        self.menu.addItem("", lambda: print(""), None)
        self.menu.addItem("Power Off", self.power_down, None)

    def populate_load_menu(self):
        self.load_menu.menu_items.clear()
        data_folder_path = self.get_storage_dir()
        try:
            files = [f for f in os.listdir(data_folder_path) if os.path.isfile(os.path.join(data_folder_path, f)) and f.endswith('.txt')]
            files.sort(key=lambda x: os.path.getmtime(os.path.join(data_folder_path, x)), reverse=True)

            self.load_menu.addItem("<- Back | Del: ctrl+bkspc", self.hide_child_menu, None)

            for filename in files:
                self.load_menu.addItem(filename, lambda f=filename: self.load_text_content(f), None)
        except Exception as e:
            self.load_menu.addItem("Error: "+{e}, self.hide_child_menu, None)
            print(f"Failed to list files in {data_folder_path}: {e}")

    def move_to_archive(self):
        selected_item = self.load_menu.menu_items[self.load_menu.selected_item]['text']
        try:
            if selected_item not in ["<- Back | Del: ctrl+bkspc"]:  # Ensure it's not a special menu item
                selected_file = os.path.join(self.get_storage_dir(), selected_item)
                print(selected_file)
                shutil.move(selected_file, self.get_archive_dir())
                print(f"Moved {selected_item} to Archive folder.")
                self.menu.consolemsg(f"Deleted {selected_item}.")
                self.populate_load_menu()
                self.menu.display()
        except Exception as e:
            self.menu.consolemsg(f"{e}.")
            print(e)        

    def populate_networks_menu(self):
        self.networks_menu.menu_items.clear()
        try:
            available_networks = self.get_available_wifi_networks()
            self.networks_menu.addItem("<- Back", self.hide_child_menu, None)
            self.networks_menu.addItem("Manually Enter SSID", lambda: self.menu.getInput("SSID", self.input_content), lambda: self.update_manual_ssid(self.menu.input_content))
            if self.manual_network!="":
                self.networks_menu.addItem(self.manual_network, lambda: self.menu.request_network_pw(), lambda: self.connect_to_network(self.manual_network,(self.menu.input_content)))
            for network in available_networks:
                if network != "--":
                    self.networks_menu.addItem(network, lambda n=network: self.menu.request_network_pw(), lambda n=network: self.connect_to_network(n,(self.menu.input_content)))
        except Exception as e:
            self.networks_menu.addItem(f"Failed: {e}", self.hide_child_menu, None)
            print(f"Failed: {e}")

    def update_manual_ssid(self, networkname):
        self.manual_network=networkname
        self.populate_networks_menu()
        print("new network: "+ networkname)

    def connect_to_network(self, network, password):
        self.connect_to_wifi(network, password)
        return

    def check_nmcli(self):
        print("checking for networking")
        try:
            # Run nmcli to check the status of NetworkManager
            process = subprocess.Popen(['nmcli', 'general', 'status'], 
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate(timeout=5)
            print(stdout)
            print(stderr)
            if b'Error' in stderr:
                print("NetworkManager not running.")
                print("If you want network management, run: sudo systemctl enable NetworkManager")
                print("This will require you to reconfigure network in raspi-config.")
                print("You'll need a HDMI cable, since SSH won't work.")
                # Enable NetworkManager
                # subprocess.run(['sudo', 'systemctl', 'enable', 'NetworkManager'])
                # time.sleep(1)
                # subprocess.run(['sudo', 'systemctl', 'start', 'NetworkManager'])
                # time.sleep(1)
            else:
                print("NetworkManager is enabled.")
        except subprocess.TimeoutExpired:
            print("Networking not detected or configured.")

    def connect_to_wifi(self, ssid, password):
        try:
            process = subprocess.Popen(['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password], 
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Wait for the command to finish, with a timeout of 5 seconds
            stdout, stderr = process.communicate(timeout=5)
            # Check if the command was successful
            if process.returncode == 0:
                print(f"Connected to WiFi: {ssid}")
                self.menu.consolemsg(f"Connected to: {ssid}")
                return True
            else:
                print(f"Error connecting to WiFi: {stderr.decode()}")
                self.menu.consolemsg(f"Error: {stderr.decode()}")
                return False
        except subprocess.TimeoutExpired:
            print("Timeout error.")
            self.menu.consolemsg("Error: Connection Timeout.")
            return False

    def consolemsg(self, text):
        self.console_message = text
        self.needs_display_update=True

    def load_text_content(self, filename):
        file_path = os.path.join(self.get_storage_dir(), filename)
        try:
            with open(file_path, 'r') as file:
                self.text_content = file.read()
                self.input_content = None
                self.cursor_position = 0
                self.current_file_path = file_path
                self.consolemsg(filename)
        except Exception as e:
            self.consolemsg(f"[Error loading file]")
        finally:
            self.hide_menu()
            print(f"Loaded file: {filename}")

    def get_available_wifi_networks(self):
        try:
            result = subprocess.run(['nmcli', '-f', 'SSID', 'dev', 'wifi', 'list'], capture_output=True, text=True)
            output = result.stdout.strip()
            networks = [line.split()[0] for line in output.split('\n')[1:] if line.strip()]
            return networks
        except Exception as e:
            print(f"Error getting available WiFi networks: {e}")
            return []

    def new_file(self):
        # Prompt for a new filename and create a new, intentional file
        self.menu.save_as()  # reuse prompt UI ("File Name")
        # Set the callback on the currently highlighted menu item to create a new file
        # Ensure the New menu item is selected; however, callback uses selected item's callback.
        # To guarantee behavior, temporarily replace the selected item's callback.
        self.menu.menu_items[self.menu.selected_item]['callback'] = lambda: self.new_file_named(self.menu.input_content)

    def new_file_named(self, userinput):
        filename = os.path.join(self.get_storage_dir(), f'{userinput}.txt')
        self.current_file_path = filename
        # Reset current buffer for a new file
        # Create the empty file (intentional)
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'a'):
                pass
            self.menu.consolemsg("[New: ]" + f'{userinput}.txt')
        except Exception as e:
            self.menu.consolemsg("[Error creating file]")
        finally:
            self.text_content = ""
            self.input_content = ""
            self.hide_menu()

    def power_down(self):
        self.epd.Clear
        self.display_draw.rectangle((0, 0, 800, 480), fill=255)  # Clear display
        self.display_draw.text((55, 150), "ZeroWriter Powering Off", font=font24, fill=0)
        partial_buffer = self.epd.getbuffer(self.display_image)
        self.epd.display_Partial(partial_buffer)
        time.sleep(1)
        self.epd.init()
        self.epd.Clear()
        time.sleep(3)
        subprocess.run(['sudo', 'poweroff', '-f'])

    def save_content(self, file_path, text_content):
      try:
          # Ensure the directory exists
          os.makedirs(os.path.dirname(file_path), exist_ok=True)
          # Check if the file is writable or create it if it doesn't exist
          with open(file_path, 'a') as file:
              pass
          # Clear the file content before writing
          with open(file_path, 'w') as file:
              print("Saving to file:", file_path)
              print(text_content[:10] + "...")
              file.write(text_content)
      except IOError as e:
          self.consolemsg("[Error saving file]")
          print("Failed to save file:", e)

    def hide_menu(self):
        time.sleep(delay)
        self.menu_mode = False
        self.needs_display_update = True

    def show_menu(self):
        self.populate_main_menu()
        self.menu_mode = True
        if self.parent_menu != None:
            self.menu = self.parent_menu
        self.selected_item = 0
        self.menu.display()

    def update_display(self):
        self.display_updating = True
        self.display_draw.rectangle((0, 0, 800, 480), fill=255)

        print("About to display content: " + self.text_content[:10] + "...")
        # Display the previous lines with soft-wrapping
        if self.input_content is None:
            y_position = 470 - self.line_spacing
            paragraphs = self.text_content.split('\n')
        elif len(self.input_content) > 0:
            y_position = 470 - self.line_spacing * 2  # leaves room for cursor input
            paragraphs = self.text_content[:-len(self.input_content)].split('\n')
        else:
            print("Input content exists but is empty")
            y_position = 470 - self.line_spacing * 2
            paragraphs = self.text_content.split('\n')

        if len(paragraphs) > 0 and paragraphs[-1] == "":
            paragraphs = paragraphs[:-1]


        print(f"Printing {len(paragraphs)} paragraphs")

        # Build wrapped lines from logical lines (only newline on Enter)
        all_wrapped = []
        for logical_line in paragraphs:
            all_wrapped.extend(self._wrap_text(logical_line, self.chars_per_line))

        if self.input_content is None:
            self.input_content = all_wrapped[-1]
        # Determine the window of lines to show based on scrollindex
        total = len(all_wrapped)
        start_index = max(0, total - self.lines_on_screen * self.scrollindex)
        visible = all_wrapped[start_index:start_index + self.lines_on_screen]

        for line in reversed(visible[-self.lines_on_screen:]):
            self.display_draw.text((10, y_position), line, font=font24, fill=0)
            y_position -= self.line_spacing

        #Display Console Message
        if self.console_message != "":
            self.display_draw.rectangle((600, 450, 800, 480), fill=255)
            self.display_draw.text((400, 450), self.console_message, font=font24, fill=0)
            self.console_message = ""
        
        #generate display buffer for display
        partial_buffer = self.epd.getbuffer(self.display_image)
        self.epd.display_Partial(partial_buffer)
        self.last_display_update = time.time()
        self.display_updating = False
        self.needs_display_update = False

    def update_input_area(self):
        #if not self.menu_mode:
        if not self.updating_input_area and self.scrollindex==1:
            self.updating_input_area = True
            cursor_index = self.cursor_position
            self.display_draw.rectangle((0, 450, 800, 480), fill=255)  # Clear display
            temp_content = self.input_content[:cursor_index] + "|" + self.input_content[cursor_index:]
            self.display_draw.text((10, 450), str(temp_content), font=font24, fill=0)
            #self.updating_input_area = True
            partial_buffer = self.epd.getbuffer(self.display_image)
            self.epd.display_Partial(partial_buffer)
            self.updating_input_area = False

    def _wrap_text(self, text, width):
        # Soft-wrap a single logical line to a list of lines each up to width characters,
        # preferring to break at spaces; if a word exceeds width, hard-split it.
        print("Wrapping line: " + text)
        if width <= 0:
            return [text]
        words = text.split(' ')
        lines = []
        current = ''
        for w in words:
            if current == '':
                # handle very long single word
                while len(w) > width:
                    lines.append(w[:width])
                    w = w[width:]
                current = w
            else:
                sep = ' '
                candidate = current + sep + w
                if len(candidate) <= width:
                    current = candidate
                else:
                    lines.append(current)
                    print("Added wrapped line: " + current)
                    # place word on new line, splitting if necessary
                    while len(w) > width:
                        lines.append(w[:width])
                        w = w[width:]
                    current = w
        if current != '':
            lines.append(current)
        # ensure at least one line
        if not lines:
            lines = ['']
        return lines

    def _all_wrapped_lines(self):
        all_wrapped = []
        paragraphs = self.text_content.split('\n')
        for logical_line in paragraphs:
            all_wrapped.extend(self._wrap_text(logical_line, self.chars_per_line))
        return all_wrapped

    def insert_character(self, character):

        self.text_content = self.text_content + character
        self.input_content = self.input_content + character
        if len(self.input_content) > self.chars_per_line:
            print(f"Exceeded chars per line at {self.chars_per_line}")
            last_space = self.input_content.rfind(' ')
            if last_space != -1:  # if a space was found
                self.input_content = self.input_content[last_space + 1:]
                print("wrapped to next line, new input content is: " + self.input_content)
            self.needs_display_update = True
        self.cursor_position = len(self.input_content)

    def delete_character(self):
        if len(self.text_content) > 0:
            self.text_content = self.text_content[:len(self.text_content) - 1]
            if len(self.input_content) > 0:
                # Remove the character at the cursor position
                self.input_content = self.input_content[:len(self.input_content) - 1]
                self.cursor_position = len(self.input_content)  # Move the cursor back
                # self.needs_input_update = True
            #No characters on the line, move up to previous line
            else:
                self.input_content = self.text_content[len(self.text_content) - self.chars_per_line]
                self.cursor_position = len(self.input_content)
                self.needs_display_update = True
                
    def handle_key_up(self, e): 
        if e.name == 'ctrl': #if control is released
            self.control_active = False 
        if e.name == 'shift': #if shift is released
            self.shift_active = False

    def save_file(self):
        # Save to the current intentional file if set; otherwise prompt user to name the file
        if self.current_file_path:
            self.save_content(self.current_file_path, self.text_content)
            self.consolemsg("[Saved]")
        else:
            # Prompt user to name the file (intentional save)
            self.menu.save_as()
            # After user enters a name, save and set current file
            self.menu.menu_items[self.menu.selected_item]['callback'] = lambda: self.save_as_file(self.menu.input_content)

    def save_as_file(self, userinput):
        self.hide_menu
        self.hide_child_menu
        filename = os.path.join(self.get_storage_dir(), f'{userinput}.txt')
        self.current_file_path = filename
        self.save_content(filename, self.text_content)
        self.menu.consolemsg("[Save As: ]" + f'{userinput}.txt')

    def handle_key_press(self, e):
        if e.name == 'ctrl': #if control is pressed
            self.control_active = True
        if e.name == 'shift': #if shift is pressed
            self.shift_active = True

        if self.menu.inputMode:
            if len(e.name)==1:
                if self.shift_active:
                    char = keymaps.shift_mapping.get(e.name)
                    self.menu.input_content += char
                else:
                    self.menu.input_content += e.name
            if e.name=="backspace":
                self.menu.input_content = self.menu.input_content[:-1]
            if e.name=="esc":
                self.menu.input_content = ""
                self.menu.display()
                self.menu.cleanupInput()
            if e.name=="enter" and self.menu.input_content!="": #handle callback menu items
                self.menu.menu_items[self.menu.selected_item]['callback']()
                self.menu.cleanupInput()
            return

        if self.menu_mode:                
            if e.name == "w" or e.name == "up" or e.name == "left":
                self.menu.up()
            elif e.name == "s" or e.name == "down" or e.name == "right":
                self.menu.down()
            elif e.name == "enter":
                self.menu.select()
            elif e.name == "q" and self.control_active:
                self.exit()
            elif e.name == "esc":
                self.hide_menu()
            elif e.name=="backspace" and self.menu==self.load_menu and self.control_active:
                self.move_to_archive()
            elif e.name == "r" and self.control_active: #ctrl+r slow refresh
                self.epd.init()
                self.epd.Clear()
                self.menu.display()
            return
        
        if e.name == "esc":
            self.show_menu()

        if e.name== "down" and self.display_updating==False:
          self.scrollindex = self.scrollindex - 1
          if self.scrollindex < 1:
                self.scrollindex = 1
          total_wrapped = len(self._all_wrapped_lines())
          total_pages = max(1, (total_wrapped + self.lines_on_screen - 1)//self.lines_on_screen)
          current_page = max(1, total_pages - self.scrollindex + 1)
          self.consolemsg(f'[{current_page}/{total_pages}]')
          self.needs_display_update = True
          time.sleep(delay)
          

        if e.name== "up"and self.display_updating==False:
          self.scrollindex = self.scrollindex + 1
          total_wrapped = len(self._all_wrapped_lines())
          total_pages = max(1, (total_wrapped + self.lines_on_screen - 1)//self.lines_on_screen)
          if self.scrollindex > total_pages+1:
                self.scrollindex = total_pages+1
          current_page = max(1, total_pages - self.scrollindex + 1)
          self.consolemsg(f'[{current_page}/{total_pages}]')
          self.needs_display_update = True
          time.sleep(delay)


        #shortcuts:
        if e.name== "s" and self.control_active: #ctrl+s quicksave file
            self.save_file()
        if e.name== "n" and self.control_active: #ctrl+n new file
            self.new_file()
        if e.name == "r" and self.control_active: #ctrl+r slow refresh
            self.doReset = True
            
        if e.name == "backspace":
            self.delete_character()
            #self.needs_input_update = True
                
        elif e.name == "space": #space bar
            self.insert_character(" ")
            # Soft wrapping only happens at render; do not modify stored lines here

        elif e.name == "enter":
                
            # Add the input to the previous_lines array
            self.text_content = self.text_content + "\n"
            self.input_content = "" #clears input content
            self.cursor_position = 0
            # autosave to the current intentional file if one is set
            if self.current_file_path:
                self.save_content(self.current_file_path, self.text_content)
            print("Hit enter, now the text is: " + self.text_content[:10] + "...")
            self.needs_display_update = True
            
        if len(e.name) == 1 and self.control_active == False:  # letter and number input
            if self.shift_active:
                char = keymaps.shift_mapping.get(e.name)
                self.insert_character(char)
            else:
                self.insert_character(e.name)
            
        self.typing_last_time = time.time()
        #self.needs_input_update = True

    def handle_interrupt(self, signal, frame):
      self.keyboard.unhook_all()
      self.epd.init()
      self.epd.Clear()
      exit(0)

    def exit(self):
      self.keyboard.unhook_all()
      self.epd.init()
      self.epd.Clear()
      exit(0)
      
    def loop(self):
        if self.doReset:
            self.epd.init()
            self.epd.Clear()
            self.update_display()
            self.doReset = False

        if self.menu.inputMode and not self.menu.screenupdating:
            self.menu.partial_update()
        
        elif self.needs_display_update and not self.display_updating:
            self.update_display()
            self.update_input_area()
            time.sleep(delay) #*2?
            self.typing_last_time = time.time()

        elif (time.time()-self.typing_last_time)< 1:
            if not self.updating_input_area and not self.menu_mode and self.scrollindex==1:
                self.update_input_area()

    def run(self):
        # Start with no file loaded; prompt user to Load or create New via the menu
        self.show_menu()
        self.update_display()
        while True:
            self.loop()
            # This small sleep prevents zerowriter from consuming 100% cpu
            # This does not negatively affect input delay
            time.sleep(0.01)
