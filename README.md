# Task Tracker
- A simple program that allows you to track your time spent on tasks.    

### History
- In the top right of the app there is a button labelled `History`. This will show you summaries of your previous times.  
- It will show summaries for daily times recorded, as well as cumulative times spent for pay periods.  
- Pay Periods are hardcoded for the start date. They are 2 weeks long. If you wish to alter this, you will have to change the internal code. I have no current plans to make this process easy. 

### Edit
- In the history window you can edit a day's times.
- You can drag, move and stretch times.
- Left click to create a time, right click to delete it.
- Times will snap to set work hours.

### Example JSON
- I have included tasks.example.jsonl with example data so you can see the full features of the history summaries.
- Tasks.jsonl will be created on the first edit of any data, either by adding/removing a task, or by creating a day summary. Once this is done, the example file will never be used again.
- This file can be deleted without any concern.   

### Groups
- This app has a feature to add groups. This is purely cosmetic for history purposes. Tasks you group together will show a both individual and combined times in the summaries.  
- You will see them individually graphed, but they will have a similar base color.  
- You can create groups in the history section on the far right side. Use `CTRL` or `SHIFT` to select multiple tasks at a time, and then right above `Set Group`, type the name of the group you want to create.

### Settings
- Theres an icon next to the `clear` button that will open settings.
- Work hours are purely for rounding purposes, with rounding enabled the buffer zone to round to work hours is 5 minutes.
- If using timesheet functionality, set groups or tasks to assocaite with a charge code.

### Timesheet
- This app works with hourtimesheet.com. When enabled, and credentials saved in settings, it will punch you in when you start your first task of the day, and punch you out when you save times, as well as post times to the application.
- This is a little brittle so don't expect this to work perfectly all the time.
- In order to gather charge codes, it relies on your previous charge codes from the last pay period. It is recommended to put all charge codes you think you may want in the pay period before you use the app. Enter a 0 for charge codes you didn't use but may want in the future.

## Installer Command
`pyinstaller --onefile --windowed --icon=hourglass.ico --add-data "hourglass.ico;." timesheet.py`
