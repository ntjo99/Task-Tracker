### Task Tracker
- This is a simple program that allows you to track your time spent on tasks.    
- It will also store your progress in a json file that shows you a summary of time spent. This summary is grouped by pay periods, I hardcoded this, so if you want to change it you will have to alter the code.  

# Example JSON
- I have included tasks.json with example data so you can see the full features of the history summaries.
- The file will be using this file to write data, so if you do not delete this file it will append data and you will see the example data in your personal history.
- This file can be deleted without any concern, it will be rewritten on the first summary you save.

# Installer Command
`pyinstaller --onefile --windowed --icon=hourglass.ico --add-data "hourglass.ico;." timesheet.py`
