#!/bin/bash -e

. ./include/depinfo.sh

. ./include/path.sh # load $os var

[ -z "$TRAVIS" ] && TRAVIS=0 # skip steps not required for CI?
[ -z "$WGET" ] && WGET=wget # possibility of calling wget differently

if [ "$os" == "linux" ]; then
	if [ $TRAVIS -eq 0 ]; then
		hash yum &>/dev/null && {
			sudo yum install autoconf pkgconfig libtool ninja-build unzip \
			python3-pip python3-setuptools unzip wget;
			sudo pip3 install meson==1.6.0 glad2==2.0.8 Jinja2==3.1.6; }
		apt-get -v &>/dev/null && {
		    sudo apt-get update;
			sudo apt-get install -y autoconf pkg-config libtool ninja-build nasm unzip \
			python3-pip python3-setuptools unzip;
			sudo pip3 install meson==1.6.0 glad2==2.0.8 Jinja2==3.1.6; }
	fi

	if ! javac -version &>/dev/null; then
		echo "Error: missing Java Development Kit."
		hash yum &>/dev/null && \
			echo "Install it using e.g. sudo yum install java-latest-openjdk-devel"
		apt-get -v &>/dev/null && \
			echo "Install it using e.g. sudo apt-get install default-jre-headless"
		exit 255
	fi

	os_ndk="linux"
elif [ "$os" == "mac" ]; then
	if [ $TRAVIS -eq 0 ]; then
		if ! hash brew 2>/dev/null; then
			echo "Error: brew not found. You need to install Homebrew: https://brew.sh/"
			exit 255
		fi
		brew install \
			automake autoconf libtool pkg-config \
			coreutils gnu-sed wget meson ninja
	fi
	if ! javac -version &>/dev/null; then
		echo "Error: missing Java Development Kit. Install it manually."
		exit 255
	fi
fi

mkdir -p sdk && cd sdk

# Android SDK
if [ ! -d "android-sdk-${os}" ]; then
	$WGET "https://dl.google.com/android/repository/commandlinetools-${os}-${v_sdk}.zip"
	mkdir "android-sdk-${os}"
	unzip -q -d "android-sdk-${os}" "commandlinetools-${os}-${v_sdk}.zip"
	rm "commandlinetools-${os}-${v_sdk}.zip"
fi
sdkmanager () {
	local exe="./android-sdk-$os/cmdline-tools/latest/bin/sdkmanager"
	[ -x "$exe" ] || exe="./android-sdk-$os/cmdline-tools/bin/sdkmanager"
	local attempt status
	# SDK repository manifests occasionally time out on hosted runners. Installed
	# packages are reused, and all three failed attempts still fail the build.
	for attempt in 1 2 3; do
		if "$exe" --sdk_root="${ANDROID_HOME}" "$@" <<< y; then
			return 0
		else
			status=$?
		fi
		[ "$attempt" -eq 3 ] && return "$status"
		echo "SDK installation failed (attempt $attempt); retrying in 15 seconds" >&2
		sleep 15
	done
}
sdkmanager \
	"platforms;android-33" \
	"platforms;android-35" \
	"build-tools;${v_sdk_build_tools}" \
	"build-tools;34.0.0" \
	"ndk;${v_ndk}" \
	"cmake;3.22.1"

# gas-preprocessor
mkdir -p bin
$WGET "https://github.com/FFmpeg/gas-preprocessor/raw/master/gas-preprocessor.pl" \
	-O bin/gas-preprocessor.pl
chmod +x bin/gas-preprocessor.pl

cd ..
