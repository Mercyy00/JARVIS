from AppOpener import close, open as appopen
from webbrowser import open as webopen
from pywhatkit import search, playonyt
from dotenv import dotenv_values
from bs4 import BeautifulSoup
from rich import print
from groq import Groq
import webbrowser
import subprocess
import requests
import keyboard
import asyncio
import os

env_vars = dotenv_values(".env")
GroqAPIKey = env_vars.get("GroqAPIKey")

classes = ["zCubwf", "hgKELc", "LTKOO SY7ric", "ZOLcW", "gsrt vk_bk FzvWSb YwPhnf", "pclqee", "tw-Data-text tw-text-small tw-ta",
           "IZ6rdc", "05uR6d LTKOO", "vlzY6d", "webanswers-webanswers_table_webanswers-table", "dDoNo ikb4Bb gsrt", "sXLa0e", 
           "LWkfKe", "VQF4g", "qv3Wpe", "kno-rdesc", "SPZz6b"]

useragent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'

# Initialize Groq client only if API key exists
client = None
if GroqAPIKey:
    client = Groq(api_key=GroqAPIKey)

professional_responses = [
    "Your satisfaction is my top priority; feel free to reach out if there's anything else I can help you with.",
    "I'm at your service for any additional questions or support you may need—don't hesitate to ask.",
]

messages = []

SystemChatBot = [{"role": "system", "content": f"Hello, I am {os.environ.get('Username', 'User')}, a content writer. You have to write content like letters, codes, applications, essays, notes, songs, poems, etc."}]


def GoogleSearch(topic):
    search(topic)
    return True


def Content(topic):
    def OpenNotepad(file):
        try:
            default_text_editor = 'notepad.exe'
            subprocess.Popen([default_text_editor, file])
            return True
        except Exception as e:
            print(f"Error opening notepad: {e}")
            return False

    def ContentWriterAI(prompt):
        if not client:
            print("Error: Groq API key not found. Please check your .env file.")
            return "Error: Unable to generate content - API key missing."
        
        try:
            messages.append({"role": "user", "content": f"{prompt}"})

            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=SystemChatBot + messages,
                max_tokens=2048,
                temperature=0.7,
                top_p=1,
                stream=True,
                stop=None
            )

            answer = ""

            for chunk in completion:
                if chunk.choices[0].delta.content:
                    answer += chunk.choices[0].delta.content

            answer = answer.replace("</s>", "")
            messages.append({"role": "assistant", "content": answer})
            return answer
        except Exception as e:
            print(f"Error generating content: {e}")
            return f"Error: Unable to generate content - {str(e)}"

    topic = topic.replace("content", "").strip()
    content_by_ai = ContentWriterAI(topic)

    # Create Data directory if it doesn't exist
    data_dir = "Data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        print(f"Created directory: {data_dir}")

    filepath = os.path.join(data_dir, f"{topic.lower().replace(' ', '_')}.txt")
    
    try:
        with open(filepath, "w", encoding="utf-8") as file:
            file.write(content_by_ai)
        print(f"Content written to: {filepath}")
        
        OpenNotepad(filepath)
        return True
    except Exception as e:
        print(f"Error writing content to file: {e}")
        return False

# Content("write A application for sick leave")
def YouTubeSearch(topic):
    url = f"https://www.youtube.com/results?search_query={topic}"
    webbrowser.open(url)
    return True


def PlayYoutube(query):
    try:
        playonyt(query)
        return True
    except Exception as e:
        print(f"Error playing YouTube video: {e}")
        return False


# Assuming `AppOpener` and `webopen` are defined or imported
import webbrowser
import requests
from bs4 import BeautifulSoup
import subprocess
import os
import platform

import webbrowser
import requests
from bs4 import BeautifulSoup
import subprocess
import os
import platform

def OpenApp(app, sess=requests.session()):
    
    try:
        # Try to open the app using AppOpener
        appopen(app, match_closest=True, output=True, throw_error=True)
        return True

    except:
        def extract_links(html):
            if html is None:
                return []
            soup = BeautifulSoup(html, 'html.parser')
            # Find all anchors with valid href attributes
            links = soup.find_all('a', href=True)
            return [link.get('href') for link in links]
            
        def search_google(query):
            url = f"https://www.microsoft.com/en-us/search?q={query}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"}
            response = sess.get(url, headers=headers)
            if response.status_code == 200:
                return response.text
            else:
                print("Failed to retrieve search results.")
                return None

        def open_in_chrome_beta(url):
            """Open URL specifically in Google Chrome Beta"""
            system = platform.system()
            
            try:
                if system == "Windows":
                    # Common Chrome Beta paths on Windows
                    chrome_beta_paths = [
                        r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
                        r"C:\Program Files (x86)\Google\Chrome Beta\Application\chrome.exe",
                        os.path.expanduser(r"~\AppData\Local\Google\Chrome Beta\Application\chrome.exe")
                    ]
                    
                    for path in chrome_beta_paths:
                        if os.path.exists(path):
                            subprocess.run([path, url])
                            return True
                    
                    # Fallback to regular Chrome if Beta not found
                    chrome_stable_paths = [
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
                    ]
                    
                    for path in chrome_stable_paths:
                        if os.path.exists(path):
                            print("Chrome Beta not found, using stable Chrome")
                            subprocess.run([path, url])
                            return True
                
                elif system == "Darwin":  # macOS
                    # Try Chrome Beta first
                    try:
                        subprocess.run(["open", "-a", "Google Chrome Beta", url])
                        return True
                    except:
                        print("Chrome Beta not found, trying stable Chrome")
                        subprocess.run(["open", "-a", "Google Chrome", url])
                        return True
                
                elif system == "Linux":
                    # Try Chrome Beta first
                    try:
                        subprocess.run(["google-chrome-beta", url])
                        return True
                    except:
                        print("Chrome Beta not found, trying stable Chrome")
                        subprocess.run(["google-chrome", url])
                        return True
                
                # Final fallback to default browser
                print("Chrome Beta and stable Chrome not found, opening in default browser")
                webbrowser.open(url)
                return True
                
            except Exception as e:
                print(f"Error opening Chrome Beta: {e}")
                # Final fallback
                webbrowser.open(url)
                return True

        # Attempt a search for the app
        html = search_google(app)
        if html:
            links = extract_links(html)
            if links:
                link = links[0]
                open_in_chrome_beta(link)
        return True
# OpenApp("instagram")
def CloseApp(app):
    if "chrome" in app.lower():
        try:
            subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], check=True)
            print(f"Closed Chrome using taskkill")
            return True
        except:
            pass
    
    try:
        close(app, match_closest=True, output=True, throw_error=True)
        print(f"Closed {app} using AppOpener")
        return True
    except Exception as e:
        print(f"Error closing {app}: {e}")
        return False


def System(command):
    def mute():
        keyboard.press_and_release("volume mute")

    def unmute():
        keyboard.press_and_release("volume mute")

    def volume_up():
        keyboard.press_and_release("volume up")

    def volume_down():
        keyboard.press_and_release("volume down")

    try:
        if command == "mute":
            mute()
        elif command == "unmute":
            unmute()
        elif command == "volume up":
            volume_up()
        elif command == "volume down":
            volume_down()
        else:
            print(f"Unknown system command: {command}")
            return False
        
        print(f"Executed system command: {command}")
        return True
    except Exception as e:
        print(f"Error executing system command {command}: {e}")
        return False


async def TranslateAndExecute(commands: list[str]):
    funcs = []

    for command in commands:
        print(f"Processing command: {command}")
        
        if command.startswith("open "):
            app_name = command.removeprefix("open ").strip()
            fun = asyncio.to_thread(OpenApp, app_name)
            funcs.append(fun)
        elif command.startswith("close "):
            app_name = command.removeprefix("close ").strip()
            fun = asyncio.to_thread(CloseApp, app_name)
            funcs.append(fun)
        elif command.startswith("play "):
            query = command.removeprefix("play ").strip()
            fun = asyncio.to_thread(PlayYoutube, query)
            funcs.append(fun)
        elif command.startswith("content "):
            topic = command.removeprefix("content ").strip()
            fun = asyncio.to_thread(Content, topic)
            funcs.append(fun)
        elif command.startswith("google search "):
            query = command.removeprefix("google search ").strip()
            fun = asyncio.to_thread(GoogleSearch, query)
            funcs.append(fun)
        elif command.startswith("youtube search "):
            query = command.removeprefix("youtube search ").strip()
            fun = asyncio.to_thread(YouTubeSearch, query)
            funcs.append(fun)
        elif command.startswith("system "):
            sys_command = command.removeprefix("system ").strip()
            fun = asyncio.to_thread(System, sys_command)
            funcs.append(fun)
        else:
            print(f"No function found for command: {command}")

    if funcs:
        results = await asyncio.gather(*funcs, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Command {i+1} failed with exception: {result}")
            else:
                print(f"Command {i+1} result: {result}")
            yield result
    else:
        print("No valid commands to execute")

    # ...existing code...
    if "open yt music" in query:
        import webbrowser
        webbrowser.open("https://music.youtube.com/")
    elif "open settings" in query:
        import os
        os.system("start ms-settings:")
    # ...existing code...


async def Automation(commands: list[str]):
    print(f"Starting automation with commands: {commands}")
    results = []
    async for result in TranslateAndExecute(commands):
        results.append(result)
    print(f"Automation completed. Results: {results}")
    return True


    # if __name__ == "__main__":
    #     # Test with some commands
    #     test_commands = [
    #         "open notepad", 
    #         " content application for sick leave"
    #     ]
    #     print("Testing automation...")
    #     asyncio.run(Automation(test_commands))