# Task Tracker
- A simple program that allows you to track your time spent on tasks.    

### History
- In the top right of the app there is a button labelled `History`. This will show you summaries of your previous times.  
- It will show summaries for daily times recorded, as well as cumulative times spent for pay periods.  
- Pay Periods are hardcoded for the start date. They are 2 weeks long. If you wish to alter this, you will have to change the internal code. I have no current plans to make this process easy. 

### Example JSON
- I have included tasks.example.jsonl with example data so you can see the full features of the history summaries.
- Tasks.jsonl will be created on the first edit of any data, either by adding/removing a task, or by creating a day summary. Once this is done, the example file will never be used again.
- This file can be deleted without any concern.   

#### Groups
- This app has a feature to add groups. This is purely cosmetic for history purposes. Tasks you group together will show a both individual and combined times in the summaries.  
- You will see them individually graphed, but they will have a similar base color.  
- You can create groups in the history section on the far right side. Use `CTRL` or `SHIFT` to select multiple tasks at a time, and then right above `Set Group`, type the name of the group you want to create.

### Installer Command
`pyinstaller --onefile --windowed --icon=hourglass.ico --add-data "hourglass.ico;." timesheet.py`
