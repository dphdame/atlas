# ATLAS — Windows Installation Guide

## Step 1: Install Python

1. Go to **https://www.python.org/downloads/**
2. Download **Python 3.12** (click the big yellow button)
3. **IMPORTANT**: On the installer's first screen, check the box that says **"Add python.exe to PATH"**
4. Click **Install Now**
5. When it finishes, click **Close**

### Verify Python installed correctly

1. Open **Command Prompt** (press Windows key, type `cmd`, press Enter)
2. Type: `python --version`
3. It should show something like `Python 3.12.x`

If it says `'python' is not recognized`, Python was installed without the PATH option. Uninstall Python, reinstall, and make sure to check "Add python.exe to PATH."

---

## Step 2: Get the ATLAS folder

Download the shared **ATLAS** folder from OneDrive and copy it to somewhere on your computer, for example:

```
C:\Users\YourName\Documents\ATLAS
```

The folder should contain these files:
- `app.py`
- `topic_modeling.py`
- `requirements.txt`
- `_pip_helper.py`
- `setup.bat`
- `run.bat`
- `data\` folder (with test_sample.csv)
- `docs\` folder (with User Guide)

---

## Step 3: Run Setup (one time only)

1. Open **File Explorer** and navigate to the ATLAS folder
2. **Double-click `setup.bat`**
3. A black command window will open and install everything (this takes 2–5 minutes)
4. When it says **"Setup complete!"**, press any key to close

### If setup fails

- **"Python is not installed"** → Go back to Step 1
- **Red error text about pip** → Try running Command Prompt **as Administrator**, then navigate to the folder and type `setup.bat`
- **Network/proxy errors** → Make sure you have internet access; if behind a work VPN, try disconnecting

---

## Step 4: Run ATLAS

1. **Double-click `run.bat`**
2. A command window will open — do NOT close it
3. After a few seconds, your web browser will automatically open to **http://localhost:8501**
4. The ATLAS dashboard is now running

### If the browser does not open automatically

Open any browser and go to: **http://localhost:8501**

### To stop ATLAS

Close the black command window, or press **Ctrl+C** in it.

---

## Using ATLAS

1. Prepare a CSV or Excel file with a column of text responses
2. Upload the file using the sidebar
3. Select the column containing your text
4. Choose analysis mode (Guided or Automatic)
5. Click **Run Analysis**

See the **User Guide** in the `docs` folder for full details.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python` not recognized | Reinstall Python with "Add to PATH" checked |
| Setup hangs at "Installing packages" | Wait — first install can take 5 minutes |
| Browser shows "This site can't be reached" | Make sure the command window is still open and running |
| Port 8501 already in use | Close other ATLAS instances, or run: `streamlit run app.py --server.port 8502` |
| Firewall popup | Click **Allow access** — Streamlit needs to run a local web server |
| "No module named streamlit" | Run `setup.bat` again |
