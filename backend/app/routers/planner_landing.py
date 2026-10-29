"""A small public invitation landing. The bearer token stays in the URL fragment."""
import html
import json
import os
import re
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


def _ios_download_url() -> str:
    value = os.getenv('IOS_APP_DOWNLOAD_URL', '').strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
            return ''
        if parsed.hostname == 'testflight.apple.com' and re.fullmatch(r'/join/[A-Za-z0-9]{6,64}', parsed.path):
            return value
        if parsed.hostname == 'apps.apple.com' and re.fullmatch(r'/(?:[a-z]{2}/)?app/(?:[^/]+/)?id[0-9]+', parsed.path):
            return value
    except ValueError:
        pass
    return ''


@router.get("/planner/open", response_class=HTMLResponse, include_in_schema=False)
def open_planner_invitation():
    nonce = secrets.token_urlsafe(24)
    web = os.getenv("WEB_APP_URL", "").strip().rstrip("/")
    parsed = urlsplit(web)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        web = ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        web = ""
    page = _PAGE.replace("__NONCE__", html.escape(nonce, quote=True)).replace("__WEB_URL__", json.dumps(web).replace("<", "\\u003c")).replace("__IOS_DOWNLOAD_URL__", json.dumps(_ios_download_url()).replace("<", "\\u003c"))
    return HTMLResponse(page, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; connect-src 'self'; img-src 'self' https: data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        "X-Robots-Tag": "noindex, nofollow",
    })


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Your trip invitation · Trotter</title>
<style nonce="__NONCE__">
*{box-sizing:border-box}body{margin:0;background:#FAF8F2;color:#31576B;font-family:system-ui,sans-serif;min-height:100dvh;display:grid;place-items:center;padding:28px 22px}main{width:100%;max-width:430px}header{font:italic 28px Georgia,serif;margin-bottom:44px}.postcard{border:1px solid #D7DED6;padding:28px 24px 32px;min-height:250px;display:flex;flex-direction:column;justify-content:center}.eyebrow{font-size:13px;color:#647680}h1{font:normal 38px/1.1 Georgia,serif;letter-spacing:-.6px;margin:16px 0}p{line-height:1.6;font-size:15px}.dates{margin:0;color:#647680}.photo{width:100%;height:200px;object-fit:cover;margin-bottom:22px}.actions{margin-top:24px;display:grid;gap:10px}a,button{min-height:48px;padding:14px 18px;text-align:center;text-decoration:none;font:inherit;border:0;border-radius:4px;cursor:pointer}.primary{background:#31576B;color:#FAF8F2}.secondary{color:#31576B;background:transparent}.note{font-size:12px;color:#647680;margin-top:24px}a:focus-visible,button:focus-visible{outline:2px solid #AD6F4B;outline-offset:4px}[hidden]{display:none!important}.error{color:#8C4B39}
.download{border:1px solid #B7C4C6;color:#31576B;background:transparent}.install-help{font-size:14px;line-height:1.6;margin:16px 0 0;padding-left:14px;border-left:2px solid #AD6F4B}a,button{transition:transform 120ms ease-out}a:active,button:active{transform:scale(.98)}@media(prefers-reduced-motion:reduce){a,button{transition:none}a:active,button:active{transform:none}}
</style></head><body><main><header>Trotter</header><section class="postcard" aria-live="polite"><img id="photo" class="photo" hidden alt=""><div id="inviter" class="eyebrow">AN INVITATION TO TRAVEL</div><h1 id="title">A trip is waiting for you</h1><p id="dates" class="dates"></p><p id="detail">Opening your invitation…</p></section><div class="actions"><a id="native" class="primary" hidden>Open in Trotter</a><a id="download" class="download" download="Trotter.apk" referrerpolicy="no-referrer" aria-describedby="install-help" hidden>Get the Android app</a><a id="ios-download" class="download" referrerpolicy="no-referrer" aria-describedby="install-help" hidden>Get the iPhone app</a><a id="web" class="secondary" hidden>Continue in browser</a><button id="retry" class="secondary" hidden>Try again</button></div><p id="install-help" class="install-help" role="status" hidden></p><p id="privacy" class="note">You’ll review the invitation before joining. Your personal Dreams stay private.</p></main>
<script nonce="__NONCE__">
const webOrigin=__WEB_URL__;
const iosDownload=__IOS_DOWNLOAD_URL__;
const android=/Android/i.test(navigator.userAgent);
const appleMobile=/iPad|iPhone|iPod/i.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
const params=new URLSearchParams(location.hash.slice(1)), values=params.getAll('token');
const token=values.length===1&&[...params.keys()].every(key=>key==='token')&&/^[A-Za-z0-9_-]{32,128}$/.test(values[0])?values[0]:null;
const el=id=>document.getElementById(id);
async function load(){
 el('retry').hidden=true;el('native').hidden=true;el('web').hidden=true;el('download').hidden=true;el('ios-download').hidden=true;el('install-help').hidden=true;el('detail').className='';
 if(!token){el('title').textContent='This invitation is incomplete';el('detail').textContent='Ask the organiser to share a new invitation link.';return;}
 const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),12000);
 try{
  const response=await fetch('/planner/invites/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),signal:controller.signal,credentials:'omit'});
  const data=await response.json();
  if(!response.ok||['expired','revoked','unavailable'].includes(data.status)){
   el('title').textContent='This invitation is no longer active';el('detail').textContent='Ask the organiser for a new invitation.';return;
  }
  el('inviter').textContent=(data.inviter_name||'A friend')+' invited you';
  el('title').textContent=data.trip.title;
  const format=value=>new Intl.DateTimeFormat(undefined,{day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(value+'T12:00:00Z'));
  el('dates').textContent=format(data.trip.start_date)+' – '+format(data.trip.end_date);
  el('detail').textContent=data.role==='editor'?'Add your ideas, vote, and help shape the plan.':'Add your ideas and vote on where to go.';
  if(data.trip.cover_image_url){try{const photo=new URL(data.trip.cover_image_url,location.origin);if(photo.protocol==='https:'||photo.origin===location.origin){el('photo').src=photo.href;el('photo').referrerPolicy='no-referrer';el('photo').onerror=()=>{el('photo').hidden=true;};el('photo').hidden=false;}}catch{}}
  el('native').href='trotterv2://planner-invite?token='+encodeURIComponent(token);el('native').hidden=!(android||appleMobile);
  if(webOrigin){
   el('web').href=webOrigin+'/#planner-invitation='+encodeURIComponent(token);el('web').hidden=false;
   el('web').className=(android||appleMobile)?'secondary':'primary';
   el('download').href=new URL('/downloads/trotter-android.apk',webOrigin).href;
   el('download').hidden=!android;
  }
  if(appleMobile){
   if(iosDownload){el('ios-download').href=iosDownload;el('ios-download').textContent=new URL(iosDownload).hostname==='testflight.apple.com'?'Get the iPhone beta':'Get the iPhone app';el('ios-download').hidden=false;}
   el('install-help').textContent=iosDownload?'After installing Trotter, return to this invitation and tap Open in Trotter. You’ll review the trip before joining.':'Already have Trotter on your iPhone? Tap Open in Trotter. You can also join this trip in your browser.';el('install-help').hidden=false;
  }
 }catch{el('detail').textContent='Couldn’t load the invitation. Check your connection and try again.';el('detail').className='error';el('retry').hidden=false;}
 finally{clearTimeout(timeout);}
}
el('download').addEventListener('click',()=>{
 el('install-help').textContent='Open the downloaded file to install Trotter. Android may ask you to allow installs from this browser. Then return to this invitation and tap Open in Trotter.';
 el('install-help').hidden=false;
});
el('retry').addEventListener('click',load);load();
</script></body></html>"""
