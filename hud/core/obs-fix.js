// OBS Studio's Linux Browser Source (CEF) has a known bug where it flattens
// premultiplied alpha instead of compositing it — semi-transparent colors
// render as if scaled toward black. The desktop overlay (start.sh) doesn't
// go through this path and is unaffected, so this only activates when OBS
// explicitly asks for it via ?obsSafe=1, making glass panels fully opaque
// (immune to the bug) instead of translucent. The page's own background
// stays genuinely transparent — chroma-key that out in OBS instead.
if (new URLSearchParams(location.search).get('obsSafe') === '1') {
  document.documentElement.style.setProperty('--glass', 'rgb(10,16,22)');
}
