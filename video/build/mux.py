# -*- coding: utf-8 -*-
"""Обработка голоса, микс с подложкой и сборка финального mp4."""
import subprocess
import sys

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE_FX = ("highpass=f=95,lowpass=f=7200,"
            "equalizer=f=2600:t=q:w=1.4:g=-4,equalizer=f=520:t=q:w=1.2:g=2.5,"
            "acompressor=threshold=-20dB:ratio=3:attack=8:release=180,"
            "loudnorm=I=-16:TP=-1.5:LRA=11")


def run(args):
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error"] + args, check=True)


def main(video="/tmp/video_silent.mp4", voice="/tmp/voice.wav", pad="/tmp/pad.wav",
         out="/tmp/photoshop-explainer.mp4"):
    run(["-i", voice, "-af", VOICE_FX, "-ar", "44100", "-ac", "1", "/tmp/_voice_post.wav"])
    run(["-i", "/tmp/_voice_post.wav", "-i", pad, "-filter_complex",
         "[1:a]volume=0.85,highpass=f=70,lowpass=f=2600[p];"
         "[0:a][p]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.94[a]",
         "-map", "[a]", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", "/tmp/_audio.wav"])
    run(["-i", video, "-i", "/tmp/_audio.wav", "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", out])
    print("ГОТОВО:", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
