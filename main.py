import os
import random
import time
import requests
import json
import base64
import re
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

# 1. 환경 변수 및 설정
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
WP_BASE_URL = "https://virz.net" 

# 테스트 모드 설정 (True면 1개만 즉시 발행, False면 10개 랜덤 발행)
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

class NaverScraper:
    """네이버 뉴스 및 블로그 랭킹 수집 클래스"""
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }

    def get_news_ranking(self, section_id):
        url = f"https://news.naver.com/main/ranking/popularDay.naver?sectionId={section_id}"
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = soup.select(".rankingnews_list .list_title")
            cleaned_titles = []
            for t in titles[:10]:
                text = t.text.strip()
                if ']' in text[:10]:
                    text = text.split(']', 1)[-1].strip()
                cleaned_titles.append(text)
            return cleaned_titles
        except Exception as e:
            print(f"뉴스 스크래핑 실패 ({section_id}): {e}", flush=True)
            return []

    def get_blog_hot_topics(self):
        url = "https://section.blog.naver.com/HotTopicList.naver"
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            topics = soup.select(".list_hottopic .desc")
            return [topic.text.strip() for topic in topics[:10]]
        except Exception as e:
            print(f"블로그 핫토픽 스크래핑 실패: {e}", flush=True)
            return []

def generate_content(raw_keyword, category):
    """Gemini API를 이용한 제목, 본문, 요약, 태그, 이미지 프롬프트 통합 생성 (외부 링크 포함)"""
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    current_date = "2026년 2월 11일"
    
    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
참고용 현재 날짜는 {current_date}입니다. 이 날짜는 정보의 최신성을 판단하는 기준으로만 사용하세요.

[필수 준수 사항]
1. 주제 집중: 오직 제공된 하나의 키워드에 대해서만 깊이 있게 작성하세요.
2. 날짜 및 인사말 금지: 본문 내에 날짜나 도입부 인사를 절대 포함하지 마세요.
3. 분량: 공백 제외 3,000자 이상의 매우 상세한 내용을 작성하세요. 
4. 구텐베르크 블록 형식: 워드프레스 에디터가 인식할 수 있도록 HTML 주석 블록을 정확하게 사용하세요.
5. 이미지 프롬프트: 글의 주제를 상징하는 예술적인 대표 이미지를 위한 프롬프트를 영어로 작성하세요. 
   - 규칙: 반드시 "Professional photography style, high resolution, no text, no letters, no words"라는 문구를 포함하세요.
6. SEO 외부 링크(External Link): 본문 중간 혹은 하단에 주제와 관련된 권위 있는 외부 사이트(뉴스, 백과사전, 공식 기관 등)로 연결되는 링크를 최소 1개 포함하세요.
   - 링크는 가독성 좋게 일반 텍스트 하이퍼링크로 넣거나, 버튼 형식 블록을 사용하세요.
   - 버튼 예시: <!-- wp:buttons --><div class="wp-block-buttons"><!-- wp:button --><div class="wp-block-button"><a class="wp-block-button__link" href="URL">관련 정보 자세히 보기</a></div><!-- /wp:button --></div><!-- /wp:buttons -->
"""
    
    user_query = f"""
원본 키워드: {raw_keyword}

다음 형식의 JSON으로만 응답하세요:
{{
  "title": "SEO 최적화 제목",
  "content": "구텐베르크 블록 형식이 적용된 3,000자 이상의 본문 (관련 외부 링크 버튼 포함)",
  "excerpt": "핵심 요약 1~2문장",
  "tags": "태그1,태그2,태그3,태그4,태그5",
  "image_prompt": "이미지 생성을 위한 상세한 영어 프롬프트 (텍스트 없이 사진 스타일)"
}}
"""
    
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    delays = [1, 2, 4, 8, 16]
    for delay in delays:
        try:
            response = requests.post(url, json=payload, timeout=120)
            if response.status_code == 200:
                result = response.json()
                text_content = result['candidates'][0]['content']['parts'][0]['text']
                clean_json = re.sub(r'^```json\s*|\s*```$', '', text_content.strip(), flags=re.MULTILINE)
                return json.loads(clean_json)
            elif response.status_code in [429, 500, 502, 503, 504]:
                time.sleep(delay)
                continue
            else:
                print(f"Gemini API 오류: {response.status_code}", flush=True)
                break
        except Exception as e:
            print(f"콘텐츠 생성 중 예외 발생: {e}", flush=True)
            time.sleep(delay)
            continue
    return None

def generate_featured_image(image_prompt):
    """Imagen 4.0을 사용하여 대표 이미지 생성"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    
    payload = {
        "instances": [{"prompt": image_prompt}],
        "parameters": {"sampleCount": 1}
    }
    
    try:
        response = requests.post(url, json=payload, timeout=120)
        if response.status_code == 200:
            result = response.json()
            b64_data = result['predictions'][0]['bytesBase64Encoded']
            return base64.b64decode(b64_data)
        else:
            print(f"이미지 생성 API 오류: {response.status_code}", flush=True)
            return None
    except Exception as e:
        print(f"이미지 생성 중 예외 발생: {e}", flush=True)
        return None

def upload_media_to_wp(image_bytes, filename):
    """워드프레스 미디어 라이브러리에 이미지 업로드"""
    base_url = WP_BASE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wp/v2/media"
    
    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Disposition": f"attachment; filename={filename}",
        "Content-Type": "image/png"
    }
    
    try:
        res = requests.post(url, headers=headers, data=image_bytes, timeout=60)
        if res.status_code == 201:
            return res.json()['id']
        else:
            print(f"미디어 업로드 오류: {res.status_code}", flush=True)
            return None
    except Exception as e:
        print(f"미디어 업로드 중 예외 발생: {e}", flush=True)
        return None

def get_or_create_tags(base_url, headers, tag_names_str):
    """태그 이름을 ID로 변환 (없으면 생성)"""
    if not tag_names_str:
        return []
    
    tag_names = [t.strip() for t in tag_names_str.split(',') if t.strip()]
    tag_ids = []
    
    for name in tag_names:
        try:
            search_url = f"{base_url}/wp-json/wp/v2/tags?search={name}"
            res = requests.get(search_url, headers=headers, timeout=10)
            existing_tags = res.json()
            
            found = False
            if isinstance(existing_tags, list):
                for et in existing_tags:
                    if et['name'] == name:
                        tag_ids.append(et['id'])
                        found = True
                        break
            
            if not found:
                create_url = f"{base_url}/wp-json/wp/v2/tags"
                create_res = requests.post(create_url, headers=headers, json={"name": name}, timeout=10)
                if create_res.status_code in [200, 201]:
                    tag_ids.append(create_res.json()['id'])
        except Exception as e:
            print(f"태그 처리 중 오류 ({name}): {e}", flush=True)
            
    return tag_ids

def post_to_wp(content_data, featured_media_id=None):
    """워드프레스 REST API 업로드 (특성 이미지 및 태그 포함)"""
    base_url = WP_BASE_URL.rstrip('/')
    url = f"{base_url}/wp-json/wp/v2/posts"
    
    auth_str = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json"
    }

    tag_ids = get_or_create_tags(base_url, headers, content_data.get('tags', ''))

    payload = {
        "title": content_data.get('title', ''),
        "content": content_data.get('content', ''),
        "excerpt": content_data.get('excerpt', ''),
        "tags": tag_ids,
        "status": "publish"
    }
    
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 201:
            return True
        else:
            print(f"⚠️ 워드프레스 응답 오류: {res.status_code} - {res.text}", flush=True)
            return False
    except Exception as e:
        print(f"❗ 워드프레스 연결 예외: {e}", flush=True)
        return False

def main():
    if not WP_USERNAME or not WP_APP_PASSWORD:
        print("❌ 인증 정보가 부족합니다.", flush=True)
        return

    scraper = NaverScraper()
    print("🚀 [1단계] 키워드 수집 및 정제 시작...", flush=True)
    
    jobs = [
        ("101", "경제/비즈니스"),
        ("105", "IT/테크"),
        ("103", "패션/뷰티/리빙"),
        (None, "일반/생활")
    ]
    
    candidates = []
    for sid, cat in jobs:
        titles = scraper.get_news_ranking(sid) if sid else scraper.get_blog_hot_topics()
        for t in titles[:5]:
            candidates.append({"kw": t, "cat": cat})
        time.sleep(1)

    if not candidates:
        print("❌ 수집된 키워드가 없습니다.", flush=True)
        return
        
    if IS_TEST:
        print("\n🧪 [테스트 모드] 1개 즉시 발행 시도", flush=True)
        selected = random.sample(candidates, 1)
        posting_times = [0]
    else:
        selected = random.sample(candidates, min(len(candidates), 10))
        total_seconds = 2 * 60 * 60
        posting_times = sorted([random.randint(0, total_seconds) for _ in range(len(selected))])

    last_wait = 0
    for i, item in enumerate(selected):
        wait_for_next = posting_times[i] - last_wait
        if wait_for_next > 0:
            print(f"\n⏳ 대기: {wait_for_next//60}분...", flush=True)
            time.sleep(wait_for_next)
        
        print(f"📝 콘텐츠 분석 및 생성 중: {item['kw']}", flush=True)
        content_data = generate_content(item['kw'], item['cat'])
        
        if content_data and content_data.get('title'):
            print(f"📌 최종 제목: {content_data['title']}", flush=True)
            
            media_id = None
            if content_data.get('image_prompt'):
                print(f"🖼️ 대표 이미지 생성 중...", flush=True)
                img_bytes = generate_featured_image(content_data['image_prompt'])
                if img_bytes:
                    print(f"📤 미디어 라이브러리 업로드 중...", flush=True)
                    media_id = upload_media_to_wp(img_bytes, f"featured_{int(time.time())}.png")
            
            if post_to_wp(content_data, featured_media_id=media_id):
                print(f"✅ 발행 완료: {content_data['title']}", flush=True)
            else:
                print(f"❌ 워드프레스 발행 실패", flush=True)
        else:
            print(f"❌ AI 콘텐츠 생성 실패", flush=True)
            
        last_wait = posting_times[i]

    print("\n🎉 모든 자동 포스팅 작업이 성공적으로 종료되었습니다.", flush=True)

if __name__ == "__main__":
    main()
