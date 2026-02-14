import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from PIL import Image
from datetime import datetime

# 콘솔 출력 시 한글 깨짐 방지 설정
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ==========================================
# 1. 환경 변수 및 설정
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
WP_BASE_URL = "https://virz.net" 

# 테스트 모드: True일 경우 랜덤 대기 없이 즉시 1개 발행 후 종료
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 수집 로직
# ==========================================
def load_external_links():
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "https://virz.net"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if data else default_links
        except Exception as e:
            print(f"⚠️ links.json 로드 실패: {e}", flush=True)
            return default_links
    return default_links

class TrendScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        }

    def get_naver_news_custom(self, url):
        try:
            clean_url = url.strip()
            # 마크다운 링크 형식 제거용 정규식
            if clean_url.startswith('['):
                match = re.search(r'\((.*?)\)', clean_url)
                if match:
                    clean_url = match.group(1)
            
            res = requests.get(clean_url, headers=self.headers, timeout=15)
            res.encoding = res.apparent_encoding if res.apparent_encoding else 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            titles = []
            for selector in [".sa_text_strong", ".rankingnews_list .list_title", ".cluster_text_headline"]:
                items = soup.select(selector)
                if items:
                    titles.extend([t.text.strip() for t in items])
            
            unique_titles = list(dict.fromkeys([t for t in titles if t]))
            return unique_titles[:10]
        except Exception as e:
            print(f"⚠️ 스크래핑 오류 ({url[:30]}...): {e}", flush=True)
            return []

# ==========================================
# 3. 워드프레스 & 이미지 처리
# ==========================================
def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=15&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    print(f"🎨 이미지 생성 API 호출 중... (Prompt: {prompt[:30]}...)", flush=True)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    
    # 인종 및 퀄리티 보정 프롬프트 추가
    final_prompt = f"Professional commercial photography for: {prompt}. High resolution, 8k, cinematic lighting, sharp focus. Strictly NO TEXT, NO LETTERS, NO WORDS."
    
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            b64_data = result['predictions'][0]['bytesBase64Encoded']
            img_data = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGB': img = img.convert('RGB')
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=85, optimize=True)
            print("✨ 이미지 생성 완료!", flush=True)
            return out.getvalue()
        else:
            print(f"❌ 이미지 생성 실패 (HTTP {response.status_code})", flush=True)
    except Exception as e:
        print(f"❌ 이미지 생성 중 오류: {e}", flush=True)
    return None

def upload_to_wp_media(img_data):
    print("📤 워드프레스 미디어 업로드 중...", flush=True)
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201:
            media_id = res.json()['id']
            print(f"✅ 미디어 업로드 성공 (ID: {media_id})", flush=True)
            return media_id
    except Exception as e:
        print(f"❌ 미디어 업로드 중 오류: {e}", flush=True)
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성
# ==========================================
def generate_article(keyword, category_hint, internal_posts, user_links, current_date):
    print(f"🤖 Gemini API를 통한 콘텐츠 생성 시작...", flush=True)
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    internal_ref = "내 블로그 추천글 (필수 2개 이상 포함):\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in selected_int])
    
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "외부 링크 (필수 2개 이상 포함):\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 매우 상세하고 사람이 직접 작성한 것 같은 품질의 블로그 글을 작성하세요.

[현재 시점 정보]
- 오늘 날짜는 {current_date}입니다. 이 날짜를 기준으로 시의성 있는 정보를 제공하세요.

[카테고리 선택 가이드]
- 아래 제공된 카테고리 리스트 중 본문의 내용과 가장 잘 어울리는 하나를 반드시 선택하여 'category' 필드에 담으세요.
- 리스트: 트렌드, 건강정보, 여행/레저, 패션/뷰티, 공연/전시
- 기본값은 '트렌드'입니다.

[이미지 프롬프트 가이드]
- 'image_prompt' 작성 시, 인물이 포함될 경우 기본적으로 'Korean person' 또는 'East Asian'으로 묘사하세요. 
- 문맥에 따라 인종을 변경할 수 있습니다.

[필수 사항: 워드프레스 구텐베르크 블록 형식]
- 모든 콘텐츠는 구텐베르크 블록 주석(<!-- wp:... -->)으로 감싸야 합니다.

[필수 가이드: 휴먼 라이팅 및 가독성]
1. 도입부: 인사말 금지. 본론으로 즉시 시작.
2. 소제목 규칙: 숫자나 기호(1., 가., 첫째)를 절대 사용하지 마세요.
3. 가독성 최적화: 한 문단은 3~5줄 내외의 충분한 길이를 갖도록 작성하세요. 너무 짧거나 듬성듬성해 보이지 않게 하세요.
4. JSON 무결성: 답변이 끊기지 않도록 끝까지 완성하여 유효한 JSON을 출력하세요.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n수집분류힌트: {category_hint}"
    
    response_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "category": {"type": "string", "enum": ["트렌드", "건강정보", "여행/레저", "패션/뷰티", "공연/전시"]},
            "content": {"type": "string"},
            "excerpt": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "image_prompt": {"type": "string"}
        },
        "required": ["title", "category", "content", "excerpt", "tags", "image_prompt"]
    }

    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "maxOutputTokens": 8192
        }
    }
    
    for i in range(5):
        try:
            res = requests.post(url, json=payload, timeout=240)
            if res.status_code == 200:
                raw_response = res.json()['candidates'][0]['content']['parts'][0]['text']
                json_str = raw_response.strip()
                if json_str.startswith("```"):
                    json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                    json_str = re.sub(r'\s*`{3}$', '', json_str)
                json_str = "".join(c for c in json_str if ord(c) >= 32 or c in '\n\r\t')
                data = json.loads(json_str)
                print(f"✅ AI 콘텐츠 생성 완료! (선택 카테고리: {data.get('category')})", flush=True)
                return data
            else:
                print(f"⚠️ API 호출 실패 (HTTP {res.status_code}). 재시도 중... ({i+1}/5)", flush=True)
            time.sleep(2**i)
        except Exception as e:
            print(f"⚠️ 오류 발생: {e}. 재시도 중... ({i+1}/5)", flush=True)
            time.sleep(2**i)
    return None

# ==========================================
# 5. 워드프레스 발행 로직
# ==========================================
def get_or_create_term(taxonomy, name, auth):
    """워드프레스의 카테고리나 태그 ID를 조회하거나 생성"""
    endpoint = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/{taxonomy}"
    try:
        # 검색
        r = requests.get(f"{endpoint}?search={name}", auth=auth, timeout=10)
        if r.status_code == 200:
            terms = r.json()
            for t in terms:
                if t['name'].lower() == name.lower():
                    return t['id']
        
        # 생성
        cr = requests.post(endpoint, auth=auth, json={"name": name}, timeout=10)
        if cr.status_code == 201:
            return cr.json()['id']
    except Exception as e:
        print(f"⚠️ {taxonomy} 처리 오류 ({name}): {e}", flush=True)
    return None

def post_article(data, mid):
    print("📢 워드프레스 포스팅 발행 중...", flush=True)
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    # 카테고리 처리
    cat_name = data.get('category', '트렌드')
    cat_id = get_or_create_term('categories', cat_name, auth)
    
    # 태그 처리
    tag_ids = []
    tags_raw = data.get('tags', [])
    for tname in tags_raw:
        tid = get_or_create_term('tags', tname, auth)
        if tid: tag_ids.append(tid)

    payload = {
        "title": data.get('title', '제목 없음'), 
        "content": data.get('content', ''), 
        "excerpt": data.get('excerpt', ''),
        "categories": [cat_id] if cat_id else [],
        "tags": tag_ids, 
        "featured_media": mid, 
        "status": "publish"
    }
    
    try:
        res = requests.post(url, auth=auth, json=payload, timeout=40)
        if res.status_code == 201:
            print(f"🚀 포스팅 발행 성공! (Link: {res.json().get('link')})", flush=True)
            return True
        else:
            print(f"❌ 발행 실패 (HTTP {res.status_code}): {res.text}", flush=True)
    except Exception as e:
        print(f"❌ 워드프레스 API 발행 오류: {e}", flush=True)
    return False

# ==========================================
# 6. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY 누락", flush=True); return

    now = datetime(2026, 2, 14, 11, 4)
    current_date_str = now.strftime("%Y년 %m월 %d일 %H시 %M분")

    if not IS_TEST:
        start_delay = random.randint(0, 3300) 
        print(f"⏳ {start_delay // 60}분 대기 후 시작합니다...", flush=True)
        time.sleep(start_delay)

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = TrendScraper()
    
    # 수집 대상 섹션
    jobs = [
        ("[https://news.naver.com/section/102](https://news.naver.com/section/102)", "사회/생활"),
        ("[https://news.naver.com/section/105](https://news.naver.com/section/105)", "IT/기술"),
        ("[https://news.naver.com/breakingnews/section/103/241](https://news.naver.com/breakingnews/section/103/241)", "건강정보"),
        ("[https://news.naver.com/breakingnews/section/103/237](https://news.naver.com/breakingnews/section/103/237)", "여행/레저"),
        ("[https://news.naver.com/breakingnews/section/103/376](https://news.naver.com/breakingnews/section/103/376)", "패션/뷰티"),
        ("[https://news.naver.com/breakingnews/section/103/242](https://news.naver.com/breakingnews/section/103/242)", "공연/전시")
    ]
    
    pool = []
    for url, cat_hint in jobs:
        print(f"📡 {cat_hint} 데이터 수집 중...", flush=True)
        items = scraper.get_naver_news_custom(url)
        for i in items: pool.append({"kw": i, "cat_hint": cat_hint})
    
    if not pool: 
        print("❌ 수집된 데이터가 없습니다.", flush=True)
        return
    
    targets = random.sample(pool, 1)
    
    for item in targets:
        print(f"📝 대상 키워드: '{item['kw']}'", flush=True)
        data = generate_article(item['kw'], item['cat_hint'], recent_posts, user_links, current_date_str)
        
        if not data:
            print("❌ AI 콘텐츠 생성 실패로 종료합니다.", flush=True)
            continue
        
        mid = None
        if data.get('image_prompt'):
            img_data = generate_image_process(data['image_prompt'])
            if img_data: 
                mid = upload_to_wp_media(img_data)
        
        if post_article(data, mid):
            print(f"🏁 [{item['kw']}] 작업 완료!", flush=True)
        else:
            print("❌ 최종 발행 단계에서 오류가 발생했습니다.", flush=True)

if __name__ == "__main__":
    main()
