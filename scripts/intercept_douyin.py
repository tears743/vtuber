import asyncio
video_urls = []
async def on_resp(response):
    url = response.url
    if 'douyinvod' in url or 'bytecdn' in url or 'byteicdn' in url:
        video_urls.append(url)
page.on("response", on_resp)
await page.reload(wait_until="networkidle", timeout=15000)
await asyncio.sleep(5)
if video_urls:
    for u in video_urls[:5]:
        print(u[:200])
else:
    print("NONE")
