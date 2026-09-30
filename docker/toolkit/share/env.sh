# narratty toolkit: settings for good-looking recordings. Source it from sh, bash or zsh:
#   . /usr/local/share/narratty/env.sh
NARRATTY_TOOLKIT=${NARRATTY_TOOLKIT:-/usr/local/share/narratty}
export NARRATTY_TOOLKIT
export YAZI_CONFIG_HOME="$NARRATTY_TOOLKIT/yazi"
export BAT_CONFIG_PATH="$NARRATTY_TOOLKIT/bat/config"
