"""用 headed browser 获取抖音视频数据"""
import subprocess
import sys
import time

url = "https://www.douyin.com/video/7654485758779690278"
session = "dy_headed"

# open page with headed mode
subprocess.run(
    ["browser", "--headed", "--session", session, "open", url],
    capture_output=True, text=True, timeout=30,
    encoding="utf-8", errors="replace",
)
time.sleep(10)

# search for video data in RENDER_DATA
js = """(function(){
    try {
        var el = document.getElementById('RENDER_DATA');
        if (!el) return 'NO_RENDER_DATA';
        var raw = decodeURIComponent(el.textContent);
        var len = raw.length;
        // find video detail
        var idx = raw.indexOf('awemeDetail');
        if (idx === -1) idx = raw.indexOf('aweme_detail');
        if (idx > -1) return 'AWEME_AT:' + idx + '|TOTAL:' + len + '|DATA:' + raw.substring(idx, idx+3000);
        // find play URL directly
        idx = raw.indexOf('play_addr');
        if (idx === -1) idx = raw.indexOf('playAddr');
        if (idx > -1) return 'PLAY_AT:' + idx + '|DATA:' + raw.substring(idx, idx+2000);
        // find CDN
        idx = raw.indexOf('douyinvod');
        if (idx > -1) return 'CDN_AT:' + idx + '|DATA:' + raw.substring(Math.max(0,idx-100), idx+500);
        // keys
        var data = JSON.parse(raw);
        var keys = Object.keys(data);
        var subkeys = {};
        keys.forEach(function(k){ subkeys[k] = typeof data[k] === 'object' ? Object.keys(data[k]).slice(0,10) : typeof data[k]; });
        return 'KEYS:' + JSON.stringify(subkeys) + '|TOTAL:' + len;
    } catch(e) { return 'ERROR:' + e.message; }
})()"""

result = subprocess.run(
    ["browser", "--session", session, "eval", js],
    capture_output=True, text=True, timeout=15,
    encoding="utf-8", errors="replace",
)

output = result.stdout.strip()
if "result:" in output:
    output = output.split("result:", 1)[1].strip()

print(output[:3000])

# close
subprocess.run(
    ["browser", "--session", session, "close"],
    capture_output=True, text=True, timeout=5,
)
