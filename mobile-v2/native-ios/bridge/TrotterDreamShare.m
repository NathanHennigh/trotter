#import <React/RCTBridgeModule.h>

@interface RCT_EXTERN_MODULE(TrotterDreamShare, NSObject)
RCT_EXTERN_METHOD(invalidateSession:(NSInteger)revision resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(configureSession:(NSString *)apiBaseUrl ownerId:(NSInteger)ownerId token:(NSString *)token revision:(NSInteger)revision resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(listReceipts:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(flush:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(retry:(NSString *)receiptId resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(acknowledge:(NSString *)receiptId resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
RCT_EXTERN_METHOD(forgetAccount:(NSString *)apiBaseUrl ownerId:(NSInteger)ownerId resolver:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject)
@end
