from pathlib import Path
import sys

main_p, svc_p = map(Path, sys.argv[1:])
main = main_p.read_text(encoding="utf-8")
svc = svc_p.read_text(encoding="utf-8")


def method_span(src: str, marker: str):
    pos = src.index(marker)
    start = src.rfind(".method", 0, pos)
    end = src.index(".end method", pos) + len(".end method")
    return start, end, src[start:end]


def replace_method(src: str, marker: str, new_method: str):
    a, b, _ = method_span(src, marker)
    return src[:a] + new_method + src[b:]


# Recognize x.com and twitter.com as Twitter. Insert before Snapchat instead of
# depending on compiler-generated :cond labels or .line directives.
a, b, m = method_span(main, "platformName(Ljava/lang/String;)Ljava/lang/String;")
snap = '    const-string v1, "snapchat.com"'
assert m.count(snap) == 1, "platformName Snapchat anchor mismatch"
twitter = '''    const-string v1, "x.com"

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
m = m.replace(snap, twitter + snap, 1)
main = main[:a] + m + main[b:]

# Route Twitter through the foreground yt-dlp path already used by TikTok.
for marker, bundle_reg, tmp_reg, label in [
    (
        "enqueueResolved(Lcom/veektall/grab/MainActivity$ResolvedMedia;Lcom/veektall/grab/MainActivity$ResolvedBundle;)V",
        "v8",
        "v2",
        "grab_progressive_fg",
    ),
    (
        "enqueueResolvedBackground(Lcom/veektall/grab/MainActivity$ResolvedMedia;Lcom/veektall/grab/MainActivity$ResolvedBundle;)V",
        "v3",
        "v6",
        "grab_progressive_bg",
    ),
]:
    a, b, m = method_span(main, marker)
    tik = m.index('const-string v0, "TikTok"')
    needle = "    if-eqz v0, :cond_1"
    cond = m.index(needle, tik)
    route = f'''    if-nez v0, :{label}

    const-string v0, "Twitter"

    iget-object {tmp_reg}, {bundle_reg}, Lcom/veektall/grab/MainActivity$ResolvedBundle;->platform:Ljava/lang/String;

    invoke-virtual {{v0, {tmp_reg}}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v0

    if-eqz v0, :cond_1

    :{label}'''
    m = m[:cond] + route + m[cond + len(needle):]
    main = main[:a] + m + main[b:]

# Extend the existing progressive-site predicate to TikTok, X, and Twitter.
progressive_predicate = r'''.method private static isTikTokSource(Ljava/lang/String;)Z
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
svc = replace_method(svc, "isTikTokSource(Ljava/lang/String;)Z", progressive_predicate)

# The path is now shared, so remove TikTok-only wording from user-visible status.
a, b, m = method_span(main, "startTikTokDownload(Ljava/lang/String;Ljava/lang/String;)V")
m = m.replace("Starting TikTok", "Starting download")
m = m.replace("TikTok download started", "Download started")
main = main[:a] + m + main[b:]
svc = svc.replace("Starting TikTok", "Starting video")
svc = svc.replace("Downloading TikTok", "Downloading video")
main = main.replace(
    "facebook|instagram|tiktok|snapchat",
    "facebook|instagram|tiktok|twitter|snapchat",
)

assert 'const-string v0, "Twitter"' in main
assert ":grab_progressive_fg" in main
assert ":grab_progressive_bg" in main
pred = method_span(svc, "isTikTokSource(Ljava/lang/String;)Z")[2]
for host in ("x.com", "twitter.com", ".x.com", ".twitter.com"):
    assert host in pred

main_p.write_text(main, encoding="utf-8")
svc_p.write_text(svc, encoding="utf-8")
print("X_TWITTER_SMALI_PATCH_PASS")
