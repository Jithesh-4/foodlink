rec.onresult = async (ev) => {

  const spoken = ev.results[0][0].transcript

  document.getElementById('searchInput').value = spoken

  // send voice sentence to AI
  const res = await fetch('/ai/interpret',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:spoken})
  })

  const data = await res.json()

  const keywords = data.keywords

  // now filter cards already on page
  filterFoodCards(keywords)
}
function filterFoodCards(query){

  const words = query.toLowerCase().split(/\s+/)

  document.querySelectorAll('.food-card').forEach(card => {

    const text = card.innerText.toLowerCase()

    const match = words.some(word => text.includes(word))

    card.style.display = match ? 'block' : 'none'
  })
}