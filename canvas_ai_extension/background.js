//replace YOURISD.instructure.com with your actual domain

// background.js

const SERVER_ENDPOINT = "http://localhost:5000/receive_cookies";

// Triggered when the extension is installed or updated
chrome.runtime.onInstalled.addListener(() => {
  console.log("Extension installed. Attempting to send cookies...");
  sendAllCookies();
});

// Triggered when the user clicks the extension icon
chrome.action.onClicked.addListener(() => {
  console.log("Extension icon clicked. Attempting to send cookies...");
  sendAllCookies();
});

/**
 * Fetch specified cookies from YOURISD.instructure.com and my_app_cookie from localhost:5000,
 * then send them all to the server endpoint.
 */
function sendAllCookies() {
  const canvasCookieNames = [
    "_csrf_token",
    "_legacy_normandy_session",
    "canvas_session",
    "log_session_id"
  ];

  // Fetch Canvas cookies
  const canvasPromises = canvasCookieNames.map(name => {
    return new Promise(resolve => {
      chrome.cookies.get({
        url: "https://YOURISD.instructure.com",
        name: name
      }, cookie => {
        resolve(cookie);
      });
    });
  });

  // Fetch my_app_cookie from localhost:5000
  const myAppPromise = new Promise(resolve => {
    chrome.cookies.get({
      url: "http://localhost:5000",
      name: "my_app_cookie"
    }, cookie => {
      resolve(cookie);
    });
  });

  // Wait for all cookies to be fetched
  Promise.all([Promise.all(canvasPromises), myAppPromise]).then(([canvasCookies, myAppCookie]) => {
    // Filter out null cookies
    const validCanvas = canvasCookies.filter(Boolean).map(c => ({
      name: c.name,
      value: c.value,
      domain: c.domain
    }));

    let myApp = null;
    if (myAppCookie) {
      myApp = {
        name: myAppCookie.name,
        value: myAppCookie.value,
        domain: myAppCookie.domain
      };
    }

    // Combine all cookies
    const allCookiesToSend = [...validCanvas];
    if (myApp) {
      allCookiesToSend.push(myApp);
    }

    if (allCookiesToSend.length === 0) {
      console.log("No cookies found to send.");
      return;
    }

    console.log("Sending cookies to server:", allCookiesToSend);

    // Send cookies to the server
    fetch(SERVER_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookies: allCookiesToSend })
    })
    .then(response => response.json())
    .then(data => {
      console.log("Server responded:", data);
    })
    .catch(error => {
      console.error("Failed to send cookies:", error);
    });
  });
}
