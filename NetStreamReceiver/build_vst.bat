@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" amd64
if errorlevel 1 (
    echo FAILED: vcvarsall.bat
    exit /b 1
)
cd /d "%~dp0"
cmake -B build -G Ninja -DJUCE_DIR=C:/JUCE -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 (
    echo FAILED: cmake configure
    exit /b 1
)
cmake --build build --config Release
if errorlevel 1 (
    echo FAILED: cmake build
    exit /b 1
)
echo BUILD SUCCEEDED
