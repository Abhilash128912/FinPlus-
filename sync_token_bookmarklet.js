/**
 * INDmoney Sync Token Bookmarklet
 * 
 * INSTRUCTIONS:
 * 1. Create a bookmark in your browser (mobile or desktop).
 * 2. Edit the bookmark, set the name to "Sync Token".
 * 3. Copy the entire minified block below and paste it into the URL field of the bookmark.
 * 4. To run: Log in to the INDmoney web portal on your browser, then click/tap this bookmark.
 */

// MINIFIED BOOKMARKLET CODE (Paste this in the URL field of the bookmark):
// javascript:(function(){var token="";for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k.toLowerCase().includes('token')||k.toLowerCase().includes('jwt')||k.toLowerCase().includes('auth')){token=localStorage.getItem(k);break}}if(!token){for(var i=0;i<sessionStorage.length;i++){var k=sessionStorage.key(i);if(k.toLowerCase().includes('token')||k.toLowerCase().includes('jwt')||k.toLowerCase().includes('auth')){token=sessionStorage.getItem(k);break}}}if(!token){var cookies=document.cookie.split(';');for(var i=0;i<cookies.length;i++){var c=cookies[i].trim();if(c.toLowerCase().includes('token')||c.toLowerCase().includes('jwt')||c.toLowerCase().includes('auth')){token=c.split('=')[1];break}}}if(token&&token.startsWith('{')){try{var obj=JSON.parse(token);token=obj.accessToken||obj.token||obj.jwt||token}catch(e){}}if(token){var backend_url=prompt('Enter your backend API URL:',localStorage.getItem('ws_backend_url')||'http://localhost:8000');if(backend_url){localStorage.setItem('ws_backend_url',backend_url);fetch(backend_url+'/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:token})}).then(res=>{if(res.ok)alert('✅ Token synced successfully to backend!');else alert('❌ Backend returned error code: '+res.status)}).catch(err=>alert('❌ Connection failed: '+err))}}else{alert('⚠️ Auth token not found! Please make sure you are logged in to the INDmoney portal.')}})();
