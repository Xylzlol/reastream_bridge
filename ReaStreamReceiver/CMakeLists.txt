cmake_minimum_required(VERSION 3.22)
project(ReaStreamReceiver VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- JUCE ---
# Point this at your local JUCE checkout (or use CPM/FetchContent)
# e.g.  cmake -DJUCE_DIR=C:/JUCE ..
if(NOT DEFINED JUCE_DIR)
    # Try common locations
    if(EXISTS "C:/JUCE")
        set(JUCE_DIR "C:/JUCE")
    elseif(EXISTS "$ENV{USERPROFILE}/JUCE")
        set(JUCE_DIR "$ENV{USERPROFILE}/JUCE")
    else()
        message(FATAL_ERROR
            "JUCE not found. Set JUCE_DIR:\n"
            "  cmake -DJUCE_DIR=C:/path/to/JUCE ..")
    endif()
endif()

add_subdirectory(${JUCE_DIR} juce_build)

juce_add_plugin(ReaStreamReceiver
    COMPANY_NAME           "DanteDev"
    PLUGIN_MANUFACTURER_CODE Dnte
    PLUGIN_CODE             RsRx
    FORMATS                 VST3 Standalone
    PRODUCT_NAME            "ReaStream Receiver"
    NEEDS_MIDI_INPUT        FALSE
    NEEDS_MIDI_OUTPUT       FALSE
    IS_SYNTH                FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD TRUE
)

target_sources(ReaStreamReceiver PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
)

target_compile_definitions(ReaStreamReceiver PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0
)

target_link_libraries(ReaStreamReceiver PRIVATE
    juce::juce_audio_utils
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags
)

# Link Winsock on Windows
if(WIN32)
    target_link_libraries(ReaStreamReceiver PRIVATE ws2_32)
endif()
