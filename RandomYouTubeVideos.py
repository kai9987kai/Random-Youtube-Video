import gspread
from tkinter import *
from oauth2client.service_account import ServiceAccountCredentials
from pprint import pprint
import random
from tkinter import ttk
import webbrowser
scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
         "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
creds = creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)
sheet = client.open("likes").sheet1  # Open the spreadhseet
data = sheet.get_all_records()  # Get a list of all records
col = sheet.col_values(3)
random1 = random.randint(1, 24)
cell = sheet.cell(random1, 3).value


window = Tk()
window.title("Random YouTube Videos")
window.attributes("-topmost", True)
window.resizable(False, False)
window.geometry("+500+200")
window.iconbitmap('favicon.ico')
lbl = Label(window, text=cell)
lbl.pack()
def web():
    webbrowser.open_new(lbl.cget("text"))
ttk.Button(window, text="Open", command=web).pack()
def new():
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    creds = creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("likes").sheet1  # Open the spreadhseet
    data = sheet.get_all_records()  # Get a list of all records
    col = sheet.col_values(3)
    random1 = random.randint(1, 27)
    cell = sheet.cell(random1, 3).value
    lbl.configure(text=cell)

ttk.Button(window, text="NEW", command=new).pack()
window.mainloop()
