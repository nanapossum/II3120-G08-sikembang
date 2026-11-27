export async function removeMockWorker(): Promise<boolean> {
  const { serviceWorker } = navigator
  if (!serviceWorker) return false

  const workerUrl = new URL('/mockServiceWorker.js', location.origin).href
  const registration = await serviceWorker.getRegistration(location.origin)
  const workers = [registration?.active, registration?.waiting, registration?.installing].filter(
    Boolean,
  )

  if (
    registration &&
    workers.length &&
    workers.every((worker) => worker?.scriptURL === workerUrl)
  ) {
    await registration.unregister()
  }

  // Unregister affects future navigations. Reload before making any live API calls.
  return serviceWorker.controller?.scriptURL === workerUrl
}
