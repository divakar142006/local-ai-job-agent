import os
import sys
import time
from playwright.sync_api import sync_playwright

def main():
    root = r"D:\job-agent" if os.path.exists(r"D:\job-agent") else os.path.dirname(os.path.abspath(__file__))
    session_file = os.path.join(root, "linkedin_session.json")
    
    print("==================================================")
    print("🤖 Opening Chrome for LinkedIn Login Setup...")
    print("==================================================")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--start-maximized', '--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            viewport=None,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")
        
        print("\n👉 A Chrome browser window has opened.")
        print("👉 Please log in to your LinkedIn account in that browser.")
        print("👉 Once you are logged in, this window will automatically detect it and save your session!\n")
        
        # Monitor for successful login
        logged_in = False
        for i in range(120): # wait up to 4 minutes
            time.sleep(2)
            try:
                curr_url = page.url
                if any(k in curr_url for k in ['feed', 'mynetwork', 'jobs', 'messaging', 'notifications']):
                    print("\n🎉 LinkedIn Login Detected!")
                    context.storage_state(path=session_file)
                    print(f"✅ Session saved successfully to: {session_file}")
                    logged_in = True
                    break
            except Exception:
                break
                
        if not logged_in:
            try:
                context.storage_state(path=session_file)
                print(f"Session saved to: {session_file}")
            except Exception:
                pass
                
        time.sleep(3)
        browser.close()
        print("Done! You can close this terminal.")

if __name__ == "__main__":
    main()
