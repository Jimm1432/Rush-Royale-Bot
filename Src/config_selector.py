import tkinter as tk
from tkinter import messagebox
import shutil
import os

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
    try:
        if var.get() == "deck1":
            shutil.copy('./configs/deck1.ini', './config.ini')
        elif var.get() == "deck2":
            shutil.copy('./configs/deck2.ini', './config.ini')
        elif var.get() == "deck3":
            shutil.copy('./configs/deck3.ini', './config.ini')
        elif var.get() == "deck4":
            shutil.copy('./configs/deck4.ini', './config.ini')
        elif var.get() == "deck5":
            shutil.copy('./configs/deck5.ini', './config.ini')
    except FileNotFoundError:
        messagebox.showwarning("Warning", "No such file.")

# Create the "Submit" button with the copy_file command
tk.Button(root, text="Submit", command=copy_file).pack()

root.mainloop()