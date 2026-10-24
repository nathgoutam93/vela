"""Execution hosts supported by the native emitters."""
import platform

def native_supported():
    return (platform.system(), platform.machine()) in {('Linux','x86_64'),('Darwin','arm64')}
