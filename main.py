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

# 테스트 모드: True일 경우 1개만 즉시 발행하고 종료
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 로드 및 수집 로직 (지정된 네이버 섹션 대응)
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
    """네이버 뉴스 경로에서 데이터를 수집하는 스크래퍼"""
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        }

    def get_naver_news_custom(self, url):
        """네이버 뉴스 제목 수집"""
        try:
            clean_url = url.strip()
            if '](http' in clean_url:
                clean_url = clean_url.split('](')[1].split(')')[0]
            clean_url = clean_url.strip('[]() ')

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
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS."
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
            img.save(out, format='JPEG', quality=70, optimize=True)
            return out.getvalue()
    except Exception: pass
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except Exception: pass
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    internal_ref = "내 블로그 추천글:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in selected_int])
    
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "외부 링크:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 매우 상세하고 가공되지 않은 사람이 쓴 듯한 블로그 글을 작성하세요.

[필수 지침: 소제목 순서 표기 금지]
- **본문의 소제목(H2, H3, H4 등) 작성 시 리스트의 순서를 나타내는 모든 숫자와 문자를 제외하세요.**
- 제목에 순서를 매기는 행위는 금지하며 핵심 키워드 문구로만 구성하세요.

[금지 사항 - 절대 준수]
1. 제목이나 본문 어디에도 제작 지시어 관련 문구(3000자, 프롬프트 등)를 포함하지 마세요.
2. 버튼 타이틀에 'AI 권위 링크' 등 분류 명칭을 넣지 마세요.

[링크 삽입 규칙]
- 내부 링크 최소 2개, 외부 링크 최소 2개를 반드시 본문 또는 버튼 형식으로 포함하세요.

[가독성 및 어조]
- 인사말 없이 바로 본론으로 시작하세요.
- 한 문단은 3줄 내외로 유지하고 줄바꿈을 과감하게 활용하세요.

JSON 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt'.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n카테고리: {category}"
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    try:
        res = requests.post(url, json=payload, timeout=180)
        if res.status_code == 200:
            raw_response = res.json()['candidates'][0]['content']['parts'][0]['text']
            json_str = raw_response.strip()
            if json_str.startswith("```"):
                json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                json_str = re.sub(r'\s*`{3}$', '', json_str)
            json_str = "".join(c for c in json_str if ord(c) >= 32 or c in '\n\r\t')
            return json.loads(json_str)
    except Exception as e:
        print(f"⚠️ AI 콘텐츠 생성 실패: {e}", flush=True)
    return None

# ==========================================
# 5. 워드프레스 발행 로직
# ==========================================
def post_article(data, mid):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    tag_ids = []
    tags_raw = data.get('tags', [])
    if tags_raw:
        tag_names = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in str(tags_raw).split(',') if t.strip()]
        for tname in tag_names:
            try:
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tid = None
                if r.status_code == 200:
                    tags_data = r.json()
                    tid = next((t['id'] for t in tags_data if t['name'].lower() == tname.lower()), None)
                if not tid:
                    cr = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags", auth=auth, json={"name": tname}, timeout=10)
                    if cr.status_code == 201: tid = cr.json()['id']
                if tid: tag_ids.append(tid)
            except: continue

    payload = {
        "title": data.get('title', '제목 없음'), 
        "content": data.get('content', ''), 
        "excerpt": data.get('excerpt', ''),
        "tags": tag_ids, 
        "featured_media": mid, 
        "status": "publish"
    }
    
    try:
        res = requests.post(url, auth=auth, json=payload, timeout=40)
        return res.status_code == 201
    except Exception as e:
        print(f"워드프레스 API 발행 오류: {e}", flush=True)
        return False

# ==========================================
# 6. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY 누락", flush=True); return

    # [랜덤 시간 실행 로직] 스케줄러가 정각에 실행하면, 0~55분 사이 랜덤 대기 후 포스팅 시작
    if not IS_TEST:
        start_delay = random.randint(0, 3300) # 최대 55분(3300초) 대기
        print(f"⏳ 매시간 랜덤 분 발행을 위해 {start_delay // 60}분 대기 후 시작합니다...", flush=True)
        time.sleep(start_delay)

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = TrendScraper()
    
    print("🚀 SEO 지능형 엔진 기동...", flush=True)
    
    jobs = [
        ("https://news.naver.com/section/102", "사회"),
        ("https://news.naver.com/section/105", "IT/과학"),
        ("https://news.naver.com/breakingnews/section/103/241", "건강정보"),
        ("https://news.naver.com/breakingnews/section/103/237", "여행/레저"),
        ("https://news.naver.com/breakingnews/section/103/376", "패션/뷰티"),
        ("https://news.naver.com/breakingnews/section/103/242", "공연/전시")
    ]
    
    pool = []
    for url, cat in jobs:
        items = scraper.get_naver_news_custom(url)
        for i in items: pool.append({"kw": i, "cat": cat})
    
    if not pool: return
    
    # 시간당 1개씩 발행 (스케줄러에 의해 매시간 호출됨)
    num_posts = 1 
    targets = random.sample(pool, num_posts)
    
    for idx, item in enumerate(targets):
        print(f"📝 '{item['kw']}' 포스팅 생성 중...", flush=True)
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        if not data: continue
        
        mid = None
        if data.get('image_prompt'):
            img_data = generate_image_process(data['image_prompt'])
            if img_data: mid = upload_to_wp_media(img_data)
        
        if post_article(data, mid):
            print(f"✅ 발행 성공: {data.get('title')}", flush=True)
        else:
            print("❌ 발행 실패", flush=True)

if __name__ == "__main__":
    main()
