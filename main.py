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

# 한글 출력 안정성을 위해 표준 출력 인코딩 설정 (환경에 따라 필요할 수 있음)
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

IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 로드 및 수집
# ==========================================
def load_external_links():
    """links.json 파일에서 사용자 정의 링크를 불러옵니다."""
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

class NaverScraper:
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}

    def get_news_ranking(self, section_id):
        try:
            res = requests.get(f"https://news.naver.com/main/ranking/popularDay.naver?sectionId={section_id}", headers=self.headers, timeout=15)
            # 인코딩 자동 감지 및 강제 적용
            res.encoding = res.apparent_encoding if res.apparent_encoding else 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = []
            for t in soup.select(".rankingnews_list .list_title"):
                clean_title = t.text.strip()
                if clean_title:
                    titles.append(clean_title)
            return titles[:10]
        except Exception as e:
            print(f"뉴스 수집 오류: {e}", flush=True)
            return []

    def get_blog_hot_topics(self):
        try:
            res = requests.get("https://section.blog.naver.com/HotTopicList.naver", headers=self.headers, timeout=15)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            return [t.text.strip() for t in soup.select(".list_hottopic .desc")[:10]]
        except Exception as e:
            print(f"블로그 수집 오류: {e}", flush=True)
            return []

# ==========================================
# 3. 워드프레스 & 이미지 최적화
# ==========================================
def get_recent_posts():
    """내부 링크용 최근 포스트 목록 가져오기"""
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    """Gemini 2.5 Flash Image를 사용하여 썸네일 생성 및 JPG 70% 압축"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent?key={GEMINI_API_KEY}"
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS, NO FONTS."
    
    payload = {
        "contents": [{"parts": [{"text": final_prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]}
    }
    
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            # 이미지 데이터 안전하게 추출
            candidates = result.get('candidates', [])
            if not candidates: return None
            parts = candidates[0].get('content', {}).get('parts', [])
            inline_data = None
            for part in parts:
                if 'inlineData' in part:
                    inline_data = part['inlineData'].get('data')
                    break
            
            if inline_data:
                img_data = base64.b64decode(inline_data)
                img = Image.open(io.BytesIO(img_data))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                out = io.BytesIO()
                img.save(out, format='JPEG', quality=70, optimize=True)
                return out.getvalue()
    except Exception as e:
        print(f"이미지 생성 중 오류: {e}", flush=True)
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {
        "Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg",
        "Content-Type": "image/jpeg"
    }
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201:
            return res.json()['id']
    except Exception:
        pass
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    """KeyError 방지 및 지능형 본문 생성"""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    internal_ref = "내 블로그 추천글:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in internal_posts]) if internal_posts else ""
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "본문 중간 삽입용 외부 링크:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 3,000자 이상의 매우 상세하고 가치 있는 블로그 포스팅을 작성하세요.

[SEO 지침]
1. 내부 링크: 제공된 목록 중 연관된 글 1개를 골라 본문 중간에 자연스럽게 링크하세요.
2. 외부 링크: 제공된 링크 2개를 본문 흐름에 맞게 분산 배치하세요. (텍스트 또는 버튼 형식)
3. AI 권위 링크: 주제와 관련된 공신력 있는 외부 출처 URL을 직접 찾아 본문 하단에 추가하세요.

[출력 규칙]
- 반드시 JSON 형식으로만 응답하세요.
- JSON 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt' (모두 필수)
- 인사말, 날짜, 자기소개 금지. 구텐베르크 HTML 형식을 지킬 것.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n위 정보를 바탕으로 완성도 높은 포스팅 데이터를 생성하세요."
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    try:
        res = requests.post(url, json=payload, timeout=180)
        if res.status_code == 200:
            raw = res.json()['candidates'][0]['content']['parts'][0]['text']
            # JSON만 안전하게 추출
            json_str = re.search(r'\{.*\}', raw, re.DOTALL).group()
            return json.loads(json_str)
    except Exception as e:
        print(f"AI 콘텐츠 생성 실패: {e}", flush=True)
    return None

# ==========================================
# 5. 실행 및 워드프레스 발행
# ==========================================
def post_article(data, mid):
    """KeyError 방지를 위해 .get() 사용"""
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    # 태그 처리 (간략화)
    tag_ids = []
    tags_raw = data.get('tags', '')
    if tags_raw:
        for tname in [t.strip() for t in tags_raw.split(',') if t.strip()]:
            try:
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tid = next((t['id'] for t in r.json() if t['name'] == tname), None) if r.status_code == 200 else None
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
    except Exception:
        return False

def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY 누락", flush=True); return

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = NaverScraper()
    
    print("🚀 SEO 지능형 엔진 기동 중...", flush=True)
    
    jobs = [("101", "경제"), ("105", "IT/테크"), (None, "일반")]
    pool = []
    for sid, cat in jobs:
        items = scraper.get_news_ranking(sid) if sid else scraper.get_blog_hot_topics()
        for i in items[:3]: pool.append({"kw": i, "cat": cat})
        time.sleep(1)

    if not pool:
        print("❌ 수집된 키워드 없음", flush=True); return
    
    targets = random.sample(pool, 1) if IS_TEST else random.sample(pool, min(len(pool), 10))
    
    for idx, item in enumerate(targets):
        print(f"📝 [{idx+1}/{len(targets)}] '{item['kw']}' 포스팅 생성 중...", flush=True)
        
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        if not data:
            print("❌ AI 응답 데이터 파싱 실패", flush=True); continue
        
        mid = None
        if data.get('image_prompt'):
            print("🎨 대표 이미지 생성 중...", flush=True)
            img_data = generate_image_process(data['image_prompt'])
            if img_data:
                mid = upload_to_wp_media(img_data)
        
        if post_article(data, mid):
            print(f"✅ 발행 성공: {data.get('title')}", flush=True)
        else:
            print("❌ 워드프레스 발행 실패", flush=True)
            
        if not IS_TEST and idx < len(targets) - 1:
            wait = random.randint(900, 1800)
            print(f"⏳ {wait//60}분 대기 중...", flush=True)
            time.sleep(wait)

if __name__ == "__main__":
    main()
