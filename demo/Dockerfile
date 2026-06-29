# Fancy searchts demo recorder: vhs (ttyd + ffmpeg) + python + searchts + Nerd Font
FROM ghcr.io/charmbracelet/vhs

USER root

# Python + tooling for the Nerd Font install
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates fonts-jetbrains-mono curl unzip fontconfig \
 && rm -rf /var/lib/apt/lists/*

# JetBrainsMono Nerd Font (has the exact Claude Code glyphs: tool/record + result corner)
RUN mkdir -p /usr/share/fonts/nerd \
 && curl -fsSL -o /tmp/jbm.zip https://github.com/ryanoasis/nerd-fonts/releases/download/v3.2.0/JetBrainsMono.zip \
 && unzip -q /tmp/jbm.zip -d /usr/share/fonts/nerd && rm /tmp/jbm.zip \
 && fc-cache -f

# Install searchts from PyPI (curl_cffi tier + keyless search are enough for the demo)
RUN pip3 install --no-cache-dir --break-system-packages searchts

# A clean, branded prompt for the recording
RUN printf '%s\n' "PS1='\[\e[38;5;212m\]capad\[\e[0m\] \[\e[38;5;117m\]~\[\e[0m\] $ '" >> /root/.bashrc
