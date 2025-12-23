import io
import hashlib
import requests
from PIL import Image
from bs4 import BeautifulSoup
from Module.config import HEADERS

# Discord: 25MB, Telegram: 10MB (photo), 50MB (document)
DISCORD_MAX_SIZE = 25 * 1024 * 1024
TELEGRAM_MAX_SIZE = 10 * 1024 * 1024


class ImageHandler:
    def __init__(self):
        self.seen_hashes = set()

    def clear_seen_hashes(self):
        """중복 체크용 해시 캐시 초기화"""
        self.seen_hashes.clear()
        print("이미지 해시 캐시가 초기화되었습니다.")

    def compress_gif(self, image_data, target_size, filename):
        """GIF 압축 (프레임 수 줄이기 + 크기 조절)"""
        try:
            original_size = len(image_data)
            buffer = io.BytesIO(image_data)
            img = Image.open(buffer)

            if not getattr(img, 'is_animated', False):
                # 애니메이션이 아닌 GIF는 그대로 반환
                buffer.seek(0)
                return buffer, original_size

            frames = []
            durations = []

            try:
                while True:
                    frames.append(img.copy())
                    durations.append(img.info.get('duration', 100))
                    img.seek(img.tell() + 1)
            except EOFError:
                pass

            # 1단계: 프레임 수 줄이기 (2프레임마다 1개)
            if len(frames) > 10:
                step = 2
                frames = frames[::step]
                durations = [d * step for d in durations[::step]]

            # 2단계: 크기 조절 (비율 유지)
            scale = 1.0
            while scale > 0.3:
                new_width = int(frames[0].width * scale)
                new_height = int(frames[0].height * scale)

                resized_frames = [f.resize((new_width, new_height), Image.Resampling.LANCZOS)
                                  for f in frames]

                output = io.BytesIO()
                resized_frames[0].save(
                    output,
                    format='GIF',
                    save_all=True,
                    append_images=resized_frames[1:],
                    duration=durations,
                    loop=0,
                    optimize=True
                )

                if output.tell() <= target_size:
                    output.seek(0)
                    print(f"[GIF 압축] {filename}: {original_size} -> {output.tell()} bytes (scale: {scale})")
                    return output, output.tell()

                scale -= 0.1

            # 압축 실패시 원본 반환
            print(f"[GIF 압축 실패] {filename}: 목표 크기 달성 불가")
            buffer.seek(0)
            return buffer, original_size

        except Exception as e:
            print(f"[GIF 압축 에러] {filename}: {e}")
            buffer = io.BytesIO(image_data)
            return buffer, len(image_data)

    def compress_image(self, image_data, target_size, filename):
        """일반 이미지(JPG/PNG) 압축"""
        try:
            original_size = len(image_data)
            buffer = io.BytesIO(image_data)
            img = Image.open(buffer)

            # PNG를 RGB로 변환 (JPEG 저장 위해)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            quality = 95
            while quality > 20:
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=quality, optimize=True)

                if output.tell() <= target_size:
                    output.seek(0)
                    print(f"[이미지 압축] {filename}: {original_size} -> {output.tell()} bytes (quality: {quality})")
                    return output, output.tell()

                quality -= 10

            # 크기도 줄여보기
            scale = 0.8
            while scale > 0.3:
                new_size = (int(img.width * scale), int(img.height * scale))
                resized = img.resize(new_size, Image.Resampling.LANCZOS)

                output = io.BytesIO()
                resized.save(output, format='JPEG', quality=70, optimize=True)

                if output.tell() <= target_size:
                    output.seek(0)
                    print(f"[이미지 압축] {filename}: {original_size} -> {output.tell()} bytes (scale: {scale})")
                    return output, output.tell()

                scale -= 0.1

            buffer.seek(0)
            return buffer, original_size

        except Exception as e:
            print(f"[이미지 압축 에러] {filename}: {e}")
            buffer = io.BytesIO(image_data)
            return buffer, len(image_data)

    def process_image(self, image_data, filename):
        """이미지 처리 (필요시 압축) - Discord/Telegram용 두 버전 반환"""
        file_ext = filename.split('.')[-1].lower() if '.' in filename else ''
        is_gif = file_ext == 'gif' or image_data[:6] in (b'GIF87a', b'GIF89a')

        original_size = len(image_data)
        discord_compressed = False
        telegram_compressed = False

        # Discord용 (25MB 제한)
        if original_size > DISCORD_MAX_SIZE:
            if is_gif:
                discord_buffer, discord_size = self.compress_gif(image_data, DISCORD_MAX_SIZE, filename)
            else:
                discord_buffer, discord_size = self.compress_image(image_data, DISCORD_MAX_SIZE, filename)
            discord_compressed = True
            print(f"[Discord 압축] {filename}: {original_size:,} -> {discord_size:,} bytes ({(1 - discord_size / original_size) * 100:.1f}% 감소)")
        else:
            discord_buffer = io.BytesIO(image_data)

        # Telegram용 (10MB 제한)
        if original_size > TELEGRAM_MAX_SIZE:
            if is_gif:
                telegram_buffer, telegram_size = self.compress_gif(image_data, TELEGRAM_MAX_SIZE, filename)
            else:
                telegram_buffer, telegram_size = self.compress_image(image_data, TELEGRAM_MAX_SIZE, filename)
            telegram_compressed = True
            print(f"[Telegram 압축] {filename}: {original_size:,} -> {telegram_size:,} bytes ({(1 - telegram_size / original_size) * 100:.1f}% 감소)")
        else:
            telegram_buffer = io.BytesIO(image_data)

        # 압축 안 한 경우
        if not discord_compressed and not telegram_compressed:
            print(f"[압축 불필요] {filename}: {original_size:,} bytes (제한 이내)")

        discord_buffer.seek(0)
        telegram_buffer.seek(0)

        return discord_buffer, telegram_buffer, is_gif

    def download_images(self, url):
        """첫 번째 이미지만 메모리로 다운로드하여 리스트로 반환"""
        try:
            headers = HEADERS.copy()
            headers['Referer'] = url

            res = requests.get(url, headers=headers)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            image_download_contents = soup.select("div.appending_file_box ul li")
            for li in image_download_contents:
                img_tag = li.find('a', href=True)
                if not img_tag:
                    continue

                img_url = img_tag['href']
                filename = img_url.split("no=")[2] if "no=" in img_url else img_url.split("/")[-1]

                headers['Referer'] = url
                response = requests.get(img_url, headers=headers)
                image_data = response.content

                # 해시로 중복 체크
                content_hash = hashlib.sha256(image_data).hexdigest()
                if content_hash in self.seen_hashes:
                    print(f"동일한 파일이 존재합니다. PASS: {filename}")
                    continue

                self.seen_hashes.add(content_hash)

                # 이미지 처리 (압축 포함)
                discord_buffer, telegram_buffer, is_gif = self.process_image(image_data, filename)

                print(f"[메모리 버퍼] 파일명: {filename}, 원본 크기: {len(image_data)} bytes, GIF: {is_gif}")

                # 첫 번째 이미지만 반환
                return [(discord_buffer, telegram_buffer, filename, is_gif)]

            return None

        except Exception as e:
            print(f"이미지 다운로드 실패: {e}")
            return None

    # 하위 호환성을 위해 기존 메서드 유지
    def download_image(self, url):
        """단일 이미지 반환 (하위 호환성)"""
        images = self.download_images(url)
        if images:
            discord_buffer, telegram_buffer, filename, is_gif = images[0]
            return discord_buffer, telegram_buffer, filename
        return None, None, None