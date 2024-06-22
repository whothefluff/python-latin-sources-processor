import tkinter as tk
from tkinter import filedialog, messagebox


def compare_files(file1, file2):
    try:
        with open(file1, 'r') as f1, open(file2, 'r') as f2:
            f1_content = f1.read()
            f2_content = f2.read()

            if f1_content == f2_content:
                return True
            else:
                return False
    except FileNotFoundError as e:
        messagebox.showerror("Error", f"File not found: {e}")
        return None


def select_files():
    root = tk.Tk()
    root.withdraw()  # Hide the root window

    file1 = filedialog.askopenfilename(title="Select the first CSV file", filetypes=[("CSV files", "*.csv")])
    file2 = filedialog.askopenfilename(title="Select the second CSV file", filetypes=[("CSV files", "*.csv")])

    if not file1 or not file2:
        messagebox.showwarning("Selection Error", "You must select two files.")
        return

    are_identical = compare_files(file1, file2)
    if are_identical is None:
        return

    if are_identical:
        messagebox.showinfo("Result", "The files are identical.")
    else:
        messagebox.showinfo("Result", "The files are different.")


if __name__ == "__main__":
    select_files()
