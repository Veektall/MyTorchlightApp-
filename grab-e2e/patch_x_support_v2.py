from pathlib import Path
import re
import sys

main_p, svc_p = map(Path, sys.argv[1:])
main = main_p.read_text(encoding="utf-8")
svc = svc_p.read_text(encoding="utf-8")


def method_span(src, signature):
    hit = re.search(r"(?m)^\.method[^\n]*\s" + re.escape(signature) + r"\s*$", src)
    if not hit:
        raise ValueError("method declaration not found: " + signature)
    start = hit.start()
    end = src.index(".end method", hit.end()) + len(".end method")
    return start, end, src[start:end]


def replace_method(src, signature, replacement):
    a, b, _ = method_span(src, signature)
    return src[:a] + replacement + src[b:]


a, b, m = method_span(main, "platformName(Ljava/lang/String;)Ljava/lang/String;")
snap = '    const-string v1, "snapchat.com"'
assert m.count(snap) == 1
insert = '''    const-string v1, "x.com"

    invoke-direct {p0, p1, v1}, Lcom/veektall/grab/MainActivity;->hostMatches(Ljava/lang/String;Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :grab_twitter

    const-string v1, "twitter.com"
    invoke-direct {p0, p1, v1}, Lcom/veektall/grab/MainActivity;->hostMatches(Ljava/lang/String;Ljava/lang/String;)Z
    move-result v1
    if-eqz v1, :grab_after_twitter

    :grab_twitter
    const-string v0, "Twitter"
    return-object v0

    :grab_after_twitter
'''
m = m.replace(snap, insert + snap, 1)
main = main[:a] + m + main[b:]

# Final ARM64 v3.2 already contains the TikTok foreground-service fix. Its inspected
# production bytecode uses v2 for the comparison/result, v3 for bundle.platform and
# p2 for the ResolvedBundle in both foreground and background routes.
for signature, label in [
    ("enqueueResolved(Lcom/veektall/grab/MainActivity$ResolvedMedia;Lcom/veektall/grab/MainActivity$ResolvedBundle;)V", "grab_progressive_fg"),
    ("enqueueResolvedBackground(Lcom/veektall/grab/MainActivity$ResolvedMedia;Lcom/veektall/grab/MainActivity$ResolvedBundle;)V", "grab_progressive_bg"),
]:
    a, b, m = method_span(main, signature)
    p = m.index('const-string v2, "TikTok"')
    needle = "    if-eqz v2, :cond_1"
    q = m.index(needle, p)
    route = f'''    if-nez v2, :{label}

    const-string v2, "Twitter"
    iget-object v3, p2, Lcom/veektall/grab/MainActivity$ResolvedBundle;->platform:Ljava/lang/String;
    invoke-virtual {{v2, v3}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :cond_1

    :{label}'''
    m = m[:q] + route + m[q + len(needle):]
    main = main[:a] + m + main[b:]

predicate = r'''.method private static isTikTokSource(Ljava/lang/String;)Z
    .locals 3
    .param p0, "source"    # Ljava/lang/String;
    const/4 v0, 0x0
    :try_start_0
    invoke-static {p0}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {v1}, Landroid/net/Uri;->getHost()Ljava/lang/String;
    move-result-object v1
    if-nez v1, :cond_0
    return v0
    :cond_0
    sget-object v2, Ljava/util/Locale;->US:Ljava/util/Locale;
    invoke-virtual {v1, v2}, Ljava/lang/String;->toLowerCase(Ljava/util/Locale;)Ljava/lang/String;
    move-result-object v2
    const-string v1, "tiktok.com"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v1
    if-nez v1, :cond_1
    const-string v1, ".tiktok.com"
    invoke-virtual {v2, v1}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :cond_1
    const-string v1, "x.com"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v1
    if-nez v1, :cond_1
    const-string v1, ".x.com"
    invoke-virtual {v2, v1}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z
    move-result v1
    if-nez v1, :cond_1
    const-string v1, "twitter.com"
    invoke-virtual {v2, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v1
    if-nez v1, :cond_1
    const-string v1, ".twitter.com"
    invoke-virtual {v2, v1}, Ljava/lang/String;->endsWith(Ljava/lang/String;)Z
    move-result v1
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0
    if-eqz v1, :cond_2
    :cond_1
    const/4 v0, 0x1
    :cond_2
    return v0
    :catchall_0
    move-exception v1
    return v0
.end method'''
svc = replace_method(svc, "isTikTokSource(Ljava/lang/String;)Z", predicate)

a, b, m = method_span(main, "startTikTokDownload(Ljava/lang/String;Ljava/lang/String;)V")
m = m.replace("Starting TikTok", "Starting download").replace("TikTok download started", "Download started")
main = main[:a] + m + main[b:]
svc = svc.replace("Starting TikTok", "Starting video").replace("Downloading TikTok", "Downloading video")
main = main.replace("facebook|instagram|tiktok|snapchat", "facebook|instagram|tiktok|twitter|snapchat")

assert 'const-string v0, "Twitter"' in main
assert ":grab_progressive_fg" in main and ":grab_progressive_bg" in main
assert all(x in method_span(svc, "isTikTokSource(Ljava/lang/String;)Z")[2] for x in ("x.com", "twitter.com", ".x.com", ".twitter.com"))

main_p.write_text(main, encoding="utf-8")
svc_p.write_text(svc, encoding="utf-8")
print("X_TWITTER_SMALI_PATCH_PASS")
