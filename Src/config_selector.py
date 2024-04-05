import tkinter as tk
from tkinter import messagebox
import shutil
import os
import logging

# Setup logging
logging.basicConfig(filename='app.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s')
root = tk.Tk()
root.title("Deck")
# Set dark background
root.configure(background='#575559')
# Set window icon to png
root.iconbitmap('calculon.ico')
root.geometry("100x200")

def move_window(event):
    root.geometry('+{0}+{1}'.format(event.x_root, event.y_root))

var = tk.StringVar()

tk.Label(root, text="Select Deck").pack()

tk.Radiobutton(root, text="Deck 1", variable=var, value="deck1").pack()
tk.Radiobutton(root, text="Deck 2", variable=var, value="deck2").pack()
tk.Radiobutton(root, text="Deck 3", variable=var, value="deck3").pack()
tk.Radiobutton(root, text="Deck 4", variable=var, value="deck4").pack()
tk.Radiobutton(root, text="Deck 5", variable=var, value="deck5").pack()

# Define the copy_file function here
def copy_file():
    source_path = './configs/'
    dest_path = './config.ini'
    selected_deck = var.get()
    if selected_deck:
        source_file = source_path + selected_deck + '.ini'
        try:
            # Validate file paths
            if not os.path.exists(source_file):
                raise FileNotFoundError(f"The source file {source_file} does not exist.")
            if not os.path.exists(os.path.dirname(dest_path)):
                raise FileNotFoundError("The destination directory does not exist.")

            # Backup existing config.ini
            if os.path.exists(dest_path):
                shutil.copy(dest_path, dest_path + '.bak')

            # Copy the selected deck file to config.ini
            shutil.copy(source_file, dest_path)
            messagebox.showinfo("Success", "Configuration updated successfully.")
            logging.info(f"Configuration updated successfully from {selected_deck}.")
        except FileNotFoundError as e:
            messagebox.showwarning("Warning", str(e))
            logging.warning(str(e))
        except Exception as e:
            messagebox.showerror("Error", "An unexpected error occurred.")
            logging.error(str(e))
    else:
        messagebox.showwarning("Warning", "Please select a deck.")
        logging.warning("Attempted to copy file without selecting a deck.")
# Create the "Submit" button with the copy_file command
tk.Button(root, text="Submit", command=copy_file).pack()

root.mainloop()