#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/share/trans-popup"
SCRIPT="trans-popup.py"

echo "=== trans-popup 安装程序 ==="
echo ""

echo "[1/4] 检查系统依赖..."
MISSING=()
for pkg in python3-gi python3-xlib xclip ffmpeg; do
    dpkg -l "$pkg" &>/dev/null || MISSING+=("$pkg")
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "  安装缺少的包: ${MISSING[*]}"
    sudo apt-get install -y "${MISSING[@]}"
else
    echo "  系统依赖已就绪 ✓"
fi

echo "[2/4] 检查 Python 依赖..."
if ! python3 -c "import gtts" 2>/dev/null; then
    echo "  安装 gtts..."
    pip3 install --quiet gtts
else
    echo "  gtts 已就绪 ✓"
fi

echo "[3/4] 安装脚本到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT" "$INSTALL_DIR/$SCRIPT"
chmod +x "$INSTALL_DIR/$SCRIPT"
echo "  安装完成 ✓"

echo "[4/4] 设置开机自启..."
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/trans-popup.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=trans-popup
Comment=划词翻译
Exec=/usr/bin/python3 $INSTALL_DIR/$SCRIPT
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
echo "  开机自启已配置 ✓"

echo ""
echo "=== 安装完成！==="
echo ""
echo "立即启动："
echo "  python3 $INSTALL_DIR/$SCRIPT &"
echo ""
echo "使用方法：双击或划选任意英文单词即可翻译"
echo ""

read -p "是否现在启动？[Y/n] " ans
if [[ "$ans" != "n" && "$ans" != "N" ]]; then
    pkill -f trans-popup 2>/dev/null || true
    nohup python3 "$INSTALL_DIR/$SCRIPT" > /tmp/trans-popup.log 2>&1 &
    echo "已启动 (PID $!)"
fi
