@echo off
rem Builds "dist\iShow Laser.exe", a single file you can double-click (no Python needed to run it).
python -m pip install --upgrade pyinstaller pyusb libusb-package
python -m PyInstaller --noconfirm --onefile --windowed --name "iShow Laser" ^
  --add-data "firmware;firmware" --collect-all libusb_package ^
  --hidden-import fake_usb_box --hidden-import ilda --hidden-import winusb_install ishow_app.py
if exist ishow_content xcopy /E /I /Y /Q ishow_content "dist\ishow_content" >nul
echo.
echo Done: dist\iShow Laser.exe
echo Your imported laser files are kept in a "laser_files" folder next to the .exe.
pause
